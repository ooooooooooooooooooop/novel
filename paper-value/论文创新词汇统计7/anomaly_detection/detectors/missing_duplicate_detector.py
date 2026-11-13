"""
遗漏重复检测器

检测语义相似但未合并的概念对，包括同义词、缩写-全称对应、词序变化等。
使用Sentence Transformers进行语义相似性分析。
"""

import re
import numpy as np
from typing import Dict, List, Set, Tuple, Any, Optional, Iterator
from collections import defaultdict, Counter
from datetime import datetime
import logging

try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from ..core.data_models import (
    MissingDuplicate, SynonymPair, AbbreviationPair, 
    AnomalySeverity, DetectionResult
)
from ..core.exceptions import DetectionLogicException
from ..core.logging import get_logger
from ..data_access.mapping_file_manager import MappingFileManager


class MissingDuplicateDetector:
    """遗漏重复检测器
    
    检测语义相似但未合并的概念对，识别应该被合并但没有被合并的情况。
    """
    
    def __init__(self, config):
        """初始化遗漏重复检测器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取
        self.semantic_similarity_threshold = getattr(config.thresholds, 'semantic_similarity_threshold', 0.8)
        self.synonym_threshold = getattr(config.thresholds, 'synonym_threshold', 0.7)  # 经验值：降低阈值以提高检测敏感度
        self.abbreviation_threshold = getattr(config.thresholds, 'abbreviation_threshold', 0.95)
        
        # 注意：这些是经验值，需要根据实际数据调整
        self.batch_size = 100  # 经验值：批处理大小，建议根据内存情况调整
        self.max_concept_pairs = 10000  # 经验值：最大概念对数量，避免内存溢出
        
        # 语义模型
        self.semantic_model = None
        self._initialize_semantic_model()
        
        # 同义词词典（可扩展）
        self.synonym_patterns = {
            # 常见同义词模式
            'method': ['approach', 'technique', 'methodology', 'procedure'],
            'analysis': ['examination', 'investigation', 'study', 'assessment'],
            'system': ['framework', 'platform', 'architecture', 'infrastructure'],
            'model': ['framework', 'paradigm', 'schema', 'structure'],
            'data': ['information', 'dataset', 'records', 'samples'],
            'result': ['outcome', 'finding', 'conclusion', 'output'],
            'performance': ['efficiency', 'effectiveness', 'capability', 'quality'],
            'algorithm': ['procedure', 'method', 'technique', 'process']
        }
        
        # 不规则复数形式映射（用于处理不规则复数）
        self.irregular_plurals = {
            'child': 'children',
            'mouse': 'mice', 
            'foot': 'feet',
            'tooth': 'teeth',
            'person': 'people',
            'man': 'men',
            'woman': 'women',
            'datum': 'data',
            'analysis': 'analyses',
            'thesis': 'theses',
            'hypothesis': 'hypotheses',
            'criterion': 'criteria',
            'phenomenon': 'phenomena'
        }
        
        # 创建反向映射
        self.plural_to_singular = {v: k for k, v in self.irregular_plurals.items()}
        
        # 缩写模式（可扩展）
        self.abbreviation_patterns = {
            # 常见缩写模式
            'ai': 'artificial intelligence',
            'ml': 'machine learning',
            'dl': 'deep learning',
            'nlp': 'natural language processing',
            'cv': 'computer vision',
            'rnn': 'recurrent neural network',
            'cnn': 'convolutional neural network',
            'lstm': 'long short-term memory',
            'gru': 'gated recurrent unit',
            'bert': 'bidirectional encoder representations from transformers',
            'gpt': 'generative pre-trained transformer',
            'api': 'application programming interface',
            'sql': 'structured query language',
            'http': 'hypertext transfer protocol',
            'url': 'uniform resource locator',
            'json': 'javascript object notation',
            'xml': 'extensible markup language',
            'csv': 'comma-separated values'
        }
        
        self.logger.info("遗漏重复检测器初始化完成")
    
    def _initialize_semantic_model(self) -> None:
        """初始化语义相似性模型"""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            self.logger.warning("Sentence Transformers未安装，语义相似性检测将被禁用")
            return
        
        try:
            # 使用轻量级模型以平衡性能和准确性
            # 注意：这是经验选择，可根据具体需求调整模型
            model_name = 'all-MiniLM-L6-v2'  # 经验值：平衡速度和准确性的模型选择
            self.semantic_model = SentenceTransformer(model_name)
            self.logger.info(f"语义模型加载成功: {model_name}")
        except Exception as e:
            self.logger.error(f"语义模型加载失败: {e}")
            self.semantic_model = None
    
    def detect_all_anomalies(self, mapping_manager: MappingFileManager, 
                           concept_universe: Optional[Set[str]] = None) -> List[DetectionResult]:
        """检测所有遗漏重复异常
        
        Args:
            mapping_manager: 映射文件管理器
            concept_universe: 概念全集，如果不提供则从映射中提取
            
        Returns:
            检测结果列表
        """
        try:
            self.logger.info("开始遗漏重复异常检测")
            
            # 加载映射数据
            mappings = mapping_manager.load_mappings()
            
            # 获取概念全集
            if concept_universe is None:
                concept_universe = self._extract_concept_universe(mappings)
            
            all_results = []
            
            # 1. 语义相似性检测
            if self.semantic_model is not None:
                semantic_results = self.detect_semantic_similarities(mappings, concept_universe)
                all_results.extend(semantic_results)
            else:
                self.logger.warning("跳过语义相似性检测：模型未加载")
            
            # 2. 同义词检测
            synonym_results = self.detect_synonyms(mappings, concept_universe)
            all_results.extend(synonym_results)
            
            # 3. 缩写检测
            abbreviation_results = self.detect_abbreviations(mappings, concept_universe)
            all_results.extend(abbreviation_results)
            
            # 4. 词序变化检测
            word_order_results = self.detect_word_order_variations(mappings, concept_universe)
            all_results.extend(word_order_results)
            
            self.logger.info(f"遗漏重复异常检测完成，发现 {len(all_results)} 个异常")
            
            return all_results
        
        except Exception as e:
            raise DetectionLogicException(f"遗漏重复异常检测失败: {e}",
                                        detector_name="MissingDuplicateDetector")
    
    def _extract_concept_universe(self, mappings: Dict[str, str]) -> Set[str]:
        """从映射中提取概念全集
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            概念全集
        """
        concepts = set(mappings.keys())
        concepts.update(mappings.values())
        
        # 过滤掉空字符串和过短的概念
        concepts = {c for c in concepts if c and len(c.strip()) > 1}
        
        self.logger.info(f"提取概念全集: {len(concepts)} 个概念")
        return concepts
    
    def detect_semantic_similarities(self, mappings: Dict[str, str], 
                                   concept_universe: Set[str]) -> List[DetectionResult]:
        """检测语义相似但未合并的概念对
        
        Args:
            mappings: 概念映射数据
            concept_universe: 概念全集
            
        Returns:
            语义相似性异常列表
        """
        try:
            self.logger.info("开始语义相似性检测")
            
            if self.semantic_model is None:
                self.logger.warning("语义模型未加载，跳过语义相似性检测")
                return []
            
            results = []
            
            # 获取未合并的概念（不在映射源中的概念）
            unmapped_concepts = self._get_unmapped_concepts(mappings, concept_universe)
            
            if len(unmapped_concepts) < 2:
                self.logger.info("未合并概念数量不足，跳过语义相似性检测")
                return []
            
            # 限制概念数量以避免内存问题
            if len(unmapped_concepts) > self.max_concept_pairs:
                self.logger.warning(f"概念数量过多({len(unmapped_concepts)})，随机采样{self.max_concept_pairs}个")
                unmapped_concepts = list(unmapped_concepts)
                np.random.shuffle(unmapped_concepts)
                unmapped_concepts = unmapped_concepts[:self.max_concept_pairs]
            else:
                unmapped_concepts = list(unmapped_concepts)
            
            # 批量计算语义嵌入
            embeddings = self._compute_embeddings_batch(unmapped_concepts)
            
            # 计算相似度矩阵并找出高相似度对
            similar_pairs = self._find_similar_pairs(unmapped_concepts, embeddings)
            
            # 为每个相似对创建异常记录
            for concept_a, concept_b, similarity_score in similar_pairs:
                severity = self._assess_semantic_similarity_severity(similarity_score)
                
                anomaly = MissingDuplicate(
                    severity=severity,
                    description=self._generate_semantic_similarity_description(
                        concept_a, concept_b, similarity_score),
                    affected_data={
                        'concept_a': concept_a,
                        'concept_b': concept_b,
                        'similarity_score': similarity_score,
                        'similarity_type': 'semantic',
                        'threshold': self.semantic_similarity_threshold
                    },
                    suggested_fix=self._suggest_semantic_similarity_fix(concept_a, concept_b),
                    concept_a=concept_a,
                    concept_b=concept_b,
                    similarity_score=similarity_score,
                    similarity_type='semantic',
                    threshold=self.semantic_similarity_threshold
                )
                
                result = DetectionResult(
                    anomaly_id=anomaly.anomaly_id,
                    detector_name="MissingDuplicateDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=[concept_a, concept_b],
                    evidence={
                        'similarity_analysis': {
                            'concept_a': concept_a,
                            'concept_b': concept_b,
                            'similarity_score': similarity_score,
                            'threshold': self.semantic_similarity_threshold,
                            'similarity_type': 'semantic'
                        },
                        'detection_method': 'sentence_transformers'
                    },
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=min(similarity_score, 1.0),
                    detection_timestamp=anomaly.timestamp
                )
                
                results.append(result)
            
            self.logger.info(f"语义相似性检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"语义相似性检测失败: {e}")
            raise
    
    def _get_unmapped_concepts(self, mappings: Dict[str, str], 
                             concept_universe: Set[str]) -> Set[str]:
        """获取未合并的概念
        
        Args:
            mappings: 概念映射数据
            concept_universe: 概念全集
            
        Returns:
            未合并的概念集合
        """
        # 已映射的概念（作为源概念出现在映射中）
        mapped_sources = set(mappings.keys())
        
        # 未映射的概念 = 全集 - 已映射的源概念
        unmapped = concept_universe - mapped_sources
        
        self.logger.debug(f"未映射概念数量: {len(unmapped)}")
        return unmapped
    
    def _compute_embeddings_batch(self, concepts: List[str]) -> np.ndarray:
        """批量计算概念的语义嵌入
        
        Args:
            concepts: 概念列表
            
        Returns:
            嵌入矩阵
        """
        try:
            # 批量编码以提高效率
            embeddings = self.semantic_model.encode(
                concepts, 
                batch_size=self.batch_size,
                show_progress_bar=True,
                convert_to_numpy=True
            )
            
            self.logger.debug(f"计算了 {len(concepts)} 个概念的嵌入")
            return embeddings
        
        except Exception as e:
            self.logger.error(f"嵌入计算失败: {e}")
            raise
    
    def _find_similar_pairs(self, concepts: List[str], 
                          embeddings: np.ndarray) -> List[Tuple[str, str, float]]:
        """找出高相似度的概念对
        
        Args:
            concepts: 概念列表
            embeddings: 嵌入矩阵
            
        Returns:
            相似概念对列表 (concept_a, concept_b, similarity_score)
        """
        similar_pairs = []
        
        # 计算相似度矩阵
        similarity_matrix = cos_sim(embeddings, embeddings).numpy()
        
        # 找出高于阈值的相似对
        n = len(concepts)
        for i in range(n):
            for j in range(i + 1, n):  # 避免重复和自比较
                similarity = similarity_matrix[i][j]
                
                if similarity >= self.semantic_similarity_threshold:
                    similar_pairs.append((concepts[i], concepts[j], float(similarity)))
        
        # 按相似度降序排序
        similar_pairs.sort(key=lambda x: x[2], reverse=True)
        
        self.logger.debug(f"发现 {len(similar_pairs)} 个高相似度概念对")
        return similar_pairs
    
    def _assess_semantic_similarity_severity(self, similarity_score: float) -> AnomalySeverity:
        """评估语义相似性异常的严重性
        
        Args:
            similarity_score: 相似度分数
            
        Returns:
            严重性级别
        """
        if similarity_score >= 0.95:
            return AnomalySeverity.HIGH
        elif similarity_score >= 0.9:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _generate_semantic_similarity_description(self, concept_a: str, concept_b: str, 
                                                similarity_score: float) -> str:
        """生成语义相似性异常的描述
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            similarity_score: 相似度分数
            
        Returns:
            异常描述
        """
        return (f"发现语义高度相似但未合并的概念对: '{concept_a}' 和 '{concept_b}' "
                f"(相似度: {similarity_score:.3f}, 阈值: {self.semantic_similarity_threshold})")
    
    def _suggest_semantic_similarity_fix(self, concept_a: str, concept_b: str) -> str:
        """为语义相似性异常提供修复建议
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            
        Returns:
            修复建议
        """
        return (f"建议将概念 '{concept_a}' 和 '{concept_b}' 合并到统一的目标概念，"
                f"或者验证它们是否确实应该保持独立")
    
    def detect_synonyms(self, mappings: Dict[str, str], 
                       concept_universe: Set[str]) -> List[DetectionResult]:
        """检测同义词对
        
        Args:
            mappings: 概念映射数据
            concept_universe: 概念全集
            
        Returns:
            同义词异常列表
        """
        try:
            self.logger.info("开始同义词检测")
            
            results = []
            unmapped_concepts = self._get_unmapped_concepts(mappings, concept_universe)
            
            # 基于预定义同义词模式检测
            for base_word, synonyms in self.synonym_patterns.items():
                base_matches = [c for c in unmapped_concepts if base_word.lower() in c.lower()]
                synonym_matches = []
                
                for synonym in synonyms:
                    matches = [c for c in unmapped_concepts if synonym.lower() in c.lower()]
                    synonym_matches.extend(matches)
                
                # 找出可能的同义词对
                for base_concept in base_matches:
                    for synonym_concept in synonym_matches:
                        if base_concept != synonym_concept:
                            # 改进的同义词置信度计算
                            confidence = self._calculate_synonym_confidence(
                                base_concept, synonym_concept, base_word, synonyms)
                            
                            if confidence >= self.synonym_threshold:
                                severity = self._assess_synonym_severity(confidence)
                                
                                anomaly = MissingDuplicate(
                                    severity=severity,
                                    description=self._generate_synonym_description(
                                        base_concept, synonym_concept, confidence),
                                    affected_data={
                                        'concept_a': base_concept,
                                        'concept_b': synonym_concept,
                                        'similarity_score': confidence,
                                        'similarity_type': 'synonym',
                                        'base_word': base_word,
                                        'synonym_word': synonyms
                                    },
                                    suggested_fix=self._suggest_synonym_fix(base_concept, synonym_concept),
                                    concept_a=base_concept,
                                    concept_b=synonym_concept,
                                    similarity_score=confidence,
                                    similarity_type='synonym',
                                    threshold=self.synonym_threshold
                                )
                                
                                result = DetectionResult(
                                    anomaly_id=anomaly.anomaly_id,
                                    detector_name="MissingDuplicateDetector",
                                    anomaly_type=anomaly.anomaly_type,
                                    severity=anomaly.severity,
                                    description=anomaly.description,
                                    affected_entities=[base_concept, synonym_concept],
                                    evidence={
                                        'synonym_analysis': {
                                            'base_concept': base_concept,
                                            'synonym_concept': synonym_concept,
                                            'confidence_score': confidence,
                                            'base_word': base_word,
                                            'synonym_pattern': synonyms
                                        },
                                        'detection_method': 'pattern_matching'
                                    },
                                    suggested_fixes=[anomaly.suggested_fix],
                                    confidence_score=confidence,
                                    detection_timestamp=anomaly.timestamp
                                )
                                
                                results.append(result)
            
            self.logger.info(f"同义词检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"同义词检测失败: {e}")
            raise
    
    def detect_abbreviations(self, mappings: Dict[str, str], 
                           concept_universe: Set[str]) -> List[DetectionResult]:
        """检测缩写-全称对应关系
        
        Args:
            mappings: 概念映射数据
            concept_universe: 概念全集
            
        Returns:
            缩写异常列表
        """
        try:
            self.logger.info("开始缩写检测")
            
            results = []
            unmapped_concepts = self._get_unmapped_concepts(mappings, concept_universe)
            
            # 基于预定义缩写模式检测
            for abbrev, full_form in self.abbreviation_patterns.items():
                abbrev_matches = [c for c in unmapped_concepts 
                                if abbrev.lower() in c.lower().split()]
                full_matches = [c for c in unmapped_concepts 
                              if any(word in c.lower() for word in full_form.split())]
                
                # 找出可能的缩写-全称对
                for abbrev_concept in abbrev_matches:
                    for full_concept in full_matches:
                        if abbrev_concept != full_concept:
                            confidence = self._calculate_abbreviation_confidence(
                                abbrev_concept, full_concept, abbrev, full_form)
                            
                            if confidence >= self.abbreviation_threshold:
                                severity = self._assess_abbreviation_severity(confidence)
                                
                                anomaly = MissingDuplicate(
                                    severity=severity,
                                    description=self._generate_abbreviation_description(
                                        abbrev_concept, full_concept, confidence),
                                    affected_data={
                                        'abbreviation_concept': abbrev_concept,
                                        'full_form_concept': full_concept,
                                        'similarity_score': confidence,
                                        'similarity_type': 'abbreviation',
                                        'abbreviation': abbrev,
                                        'full_form': full_form
                                    },
                                    suggested_fix=self._suggest_abbreviation_fix(
                                        abbrev_concept, full_concept),
                                    concept_a=abbrev_concept,
                                    concept_b=full_concept,
                                    similarity_score=confidence,
                                    similarity_type='abbreviation',
                                    threshold=self.abbreviation_threshold
                                )
                                
                                result = DetectionResult(
                                    anomaly_id=anomaly.anomaly_id,
                                    detector_name="MissingDuplicateDetector",
                                    anomaly_type=anomaly.anomaly_type,
                                    severity=anomaly.severity,
                                    description=anomaly.description,
                                    affected_entities=[abbrev_concept, full_concept],
                                    evidence={
                                        'abbreviation_analysis': {
                                            'abbreviation_concept': abbrev_concept,
                                            'full_form_concept': full_concept,
                                            'confidence_score': confidence,
                                            'abbreviation_pattern': abbrev,
                                            'full_form_pattern': full_form
                                        },
                                        'detection_method': 'abbreviation_matching'
                                    },
                                    suggested_fixes=[anomaly.suggested_fix],
                                    confidence_score=confidence,
                                    detection_timestamp=anomaly.timestamp
                                )
                                
                                results.append(result)
            
            self.logger.info(f"缩写检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"缩写检测失败: {e}")
            raise
    
    def detect_word_order_variations(self, mappings: Dict[str, str], 
                                   concept_universe: Set[str]) -> List[DetectionResult]:
        """检测词序变化但含义相同的概念
        
        Args:
            mappings: 概念映射数据
            concept_universe: 概念全集
            
        Returns:
            词序变化异常列表
        """
        try:
            self.logger.info("开始词序变化检测")
            
            results = []
            unmapped_concepts = self._get_unmapped_concepts(mappings, concept_universe)
            unmapped_list = list(unmapped_concepts)
            
            # 比较每对概念的词序变化
            for i, concept_a in enumerate(unmapped_list):
                for concept_b in unmapped_list[i+1:]:
                    if self._are_word_order_variants(concept_a, concept_b):
                        confidence = self._calculate_word_order_confidence(concept_a, concept_b)
                        
                        if confidence >= self.semantic_similarity_threshold:
                            severity = self._assess_word_order_severity(confidence)
                            
                            anomaly = MissingDuplicate(
                                severity=severity,
                                description=self._generate_word_order_description(
                                    concept_a, concept_b, confidence),
                                affected_data={
                                    'concept_a': concept_a,
                                    'concept_b': concept_b,
                                    'similarity_score': confidence,
                                    'similarity_type': 'word_order',
                                    'word_analysis': self._analyze_word_order_difference(
                                        concept_a, concept_b)
                                },
                                suggested_fix=self._suggest_word_order_fix(concept_a, concept_b),
                                concept_a=concept_a,
                                concept_b=concept_b,
                                similarity_score=confidence,
                                similarity_type='word_order',
                                threshold=self.semantic_similarity_threshold
                            )
                            
                            result = DetectionResult(
                                anomaly_id=anomaly.anomaly_id,
                                detector_name="MissingDuplicateDetector",
                                anomaly_type=anomaly.anomaly_type,
                                severity=anomaly.severity,
                                description=anomaly.description,
                                affected_entities=[concept_a, concept_b],
                                evidence={
                                    'word_order_analysis': {
                                        'concept_a': concept_a,
                                        'concept_b': concept_b,
                                        'confidence_score': confidence,
                                        'word_difference': self._analyze_word_order_difference(
                                            concept_a, concept_b)
                                    },
                                    'detection_method': 'word_order_comparison'
                                },
                                suggested_fixes=[anomaly.suggested_fix],
                                confidence_score=confidence,
                                detection_timestamp=anomaly.timestamp
                            )
                            
                            results.append(result)
            
            self.logger.info(f"词序变化检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"词序变化检测失败: {e}")
            raise
    
    def _calculate_string_similarity(self, str1: str, str2: str) -> float:
        """计算字符串相似度
        
        Args:
            str1: 字符串1
            str2: 字符串2
            
        Returns:
            相似度分数 (0-1)
        """
        # 使用Jaccard相似度计算
        set1 = set(str1.lower().split())
        set2 = set(str2.lower().split())
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def _calculate_synonym_confidence(self, concept_a: str, concept_b: str,
                                    base_word: str, synonyms: List[str]) -> float:
        """计算同义词匹配的置信度
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            base_word: 基础词
            synonyms: 同义词列表
            
        Returns:
            置信度分数 (0-1)
        """
        # 基础分数：如果两个概念包含同义词关系
        base_score = 0.0
        
        # 检查概念A是否包含基础词，概念B是否包含同义词
        concept_a_words = set(concept_a.lower().split())
        concept_b_words = set(concept_b.lower().split())
        
        # 检查是否存在同义词关系
        has_base_in_a = base_word.lower() in concept_a_words
        has_synonym_in_b = any(syn.lower() in concept_b_words for syn in synonyms)
        
        has_base_in_b = base_word.lower() in concept_b_words  
        has_synonym_in_a = any(syn.lower() in concept_a_words for syn in synonyms)
        
        if (has_base_in_a and has_synonym_in_b) or (has_base_in_b and has_synonym_in_a):
            base_score = 0.7  # 基础同义词关系分数
            
            # 计算其他词汇的重叠度
            # 移除已识别的同义词对，计算剩余词汇的相似度
            remaining_a = concept_a_words - {base_word.lower()}
            remaining_b = concept_b_words - set(syn.lower() for syn in synonyms)
            
            if has_base_in_b and has_synonym_in_a:
                remaining_a = concept_a_words - set(syn.lower() for syn in synonyms)
                remaining_b = concept_b_words - {base_word.lower()}
            
            # 计算剩余词汇的重叠度
            if remaining_a or remaining_b:
                intersection = len(remaining_a.intersection(remaining_b))
                union = len(remaining_a.union(remaining_b))
                if union > 0:
                    overlap_score = intersection / union
                    base_score += 0.3 * overlap_score  # 最多额外加0.3分
        else:
            # 如果没有直接的同义词关系，检查不规则复数形式
            irregular_score = self._handle_irregular_plurals(concept_a, concept_b)
            if irregular_score > 0.5:  # 如果不规则复数相似度较高
                base_score = irregular_score
        
        return min(base_score, 1.0)
    
    def _handle_irregular_plurals(self, concept_a: str, concept_b: str) -> float:
        """处理不规则复数形式的相似度
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            
        Returns:
            不规则复数相似度分数 (0-1)
        """
        words_a = set(concept_a.lower().split())
        words_b = set(concept_b.lower().split())
        
        # 检查是否存在不规则复数关系
        plural_matches = 0
        total_words = len(words_a.union(words_b))
        
        if total_words == 0:
            return 0.0
        
        # 检查单数->复数映射
        for word_a in words_a:
            if word_a in self.irregular_plurals:
                plural_form = self.irregular_plurals[word_a]
                if plural_form in words_b:
                    plural_matches += 2  # 双向匹配，权重更高
        
        # 检查复数->单数映射
        for word_a in words_a:
            if word_a in self.plural_to_singular:
                singular_form = self.plural_to_singular[word_a]
                if singular_form in words_b:
                    plural_matches += 2  # 双向匹配，权重更高
        
        # 计算其他词汇的重叠
        other_overlap = len(words_a.intersection(words_b))
        
        # 综合分数
        total_matches = plural_matches + other_overlap
        return min(total_matches / total_words, 1.0)
    
    def _calculate_abbreviation_confidence(self, abbrev_concept: str, full_concept: str,
                                         abbrev: str, full_form: str) -> float:
        """计算缩写匹配的置信度
        
        Args:
            abbrev_concept: 包含缩写的概念
            full_concept: 包含全称的概念
            abbrev: 缩写
            full_form: 全称
            
        Returns:
            置信度分数 (0-1)
        """
        # 基础分数：如果概念中包含对应的缩写和全称
        base_score = 0.5
        
        # 如果缩写在概念中作为独立词出现
        if abbrev.lower() in abbrev_concept.lower().split():
            base_score += 0.2
        
        # 如果全称的关键词在概念中出现
        full_words = full_form.split()
        full_concept_words = full_concept.lower().split()
        matching_words = sum(1 for word in full_words if word in full_concept_words)
        
        if len(full_words) > 0:
            base_score += 0.3 * (matching_words / len(full_words))
        
        return min(base_score, 1.0)
    
    def _are_word_order_variants(self, concept_a: str, concept_b: str) -> bool:
        """判断两个概念是否为词序变体
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            
        Returns:
            是否为词序变体
        """
        words_a = set(concept_a.lower().split())
        words_b = set(concept_b.lower().split())
        
        # 如果词集合相同但顺序不同，则为词序变体
        return words_a == words_b and concept_a.lower() != concept_b.lower()
    
    def _calculate_word_order_confidence(self, concept_a: str, concept_b: str) -> float:
        """计算词序变化的置信度
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            
        Returns:
            置信度分数 (0-1)
        """
        words_a = concept_a.lower().split()
        words_b = concept_b.lower().split()
        
        # 如果词集合完全相同，置信度为1.0
        if set(words_a) == set(words_b):
            return 1.0
        
        # 否则计算词汇重叠度
        return self._calculate_string_similarity(concept_a, concept_b)
    
    def _analyze_word_order_difference(self, concept_a: str, concept_b: str) -> Dict[str, Any]:
        """分析词序差异
        
        Args:
            concept_a: 概念A
            concept_b: 概念B
            
        Returns:
            词序差异分析结果
        """
        words_a = concept_a.lower().split()
        words_b = concept_b.lower().split()
        
        return {
            'concept_a_words': words_a,
            'concept_b_words': words_b,
            'common_words': list(set(words_a).intersection(set(words_b))),
            'unique_to_a': list(set(words_a) - set(words_b)),
            'unique_to_b': list(set(words_b) - set(words_a)),
            'word_count_a': len(words_a),
            'word_count_b': len(words_b)
        }
    
    # 严重性评估方法
    def _assess_synonym_severity(self, confidence: float) -> AnomalySeverity:
        """评估同义词异常的严重性"""
        if confidence >= 0.95:
            return AnomalySeverity.HIGH
        elif confidence >= 0.9:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _assess_abbreviation_severity(self, confidence: float) -> AnomalySeverity:
        """评估缩写异常的严重性"""
        if confidence >= 0.98:
            return AnomalySeverity.HIGH
        elif confidence >= 0.95:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _assess_word_order_severity(self, confidence: float) -> AnomalySeverity:
        """评估词序变化异常的严重性"""
        if confidence >= 1.0:
            return AnomalySeverity.HIGH
        elif confidence >= 0.9:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    # 描述生成方法
    def _generate_synonym_description(self, concept_a: str, concept_b: str, 
                                    confidence: float) -> str:
        """生成同义词异常的描述"""
        return (f"发现可能的同义词对: '{concept_a}' 和 '{concept_b}' "
                f"(置信度: {confidence:.3f})")
    
    def _generate_abbreviation_description(self, abbrev_concept: str, full_concept: str,
                                         confidence: float) -> str:
        """生成缩写异常的描述"""
        return (f"发现可能的缩写-全称对: '{abbrev_concept}' 和 '{full_concept}' "
                f"(置信度: {confidence:.3f})")
    
    def _generate_word_order_description(self, concept_a: str, concept_b: str,
                                       confidence: float) -> str:
        """生成词序变化异常的描述"""
        return (f"发现词序不同但含义相同的概念对: '{concept_a}' 和 '{concept_b}' "
                f"(置信度: {confidence:.3f})")
    
    # 修复建议方法
    def _suggest_synonym_fix(self, concept_a: str, concept_b: str) -> str:
        """为同义词异常提供修复建议"""
        return f"建议将同义词 '{concept_a}' 和 '{concept_b}' 合并到统一的概念"
    
    def _suggest_abbreviation_fix(self, abbrev_concept: str, full_concept: str) -> str:
        """为缩写异常提供修复建议"""
        return f"建议将缩写概念 '{abbrev_concept}' 和全称概念 '{full_concept}' 合并"
    
    def _suggest_word_order_fix(self, concept_a: str, concept_b: str) -> str:
        """为词序变化异常提供修复建议"""
        return f"建议将词序不同的概念 '{concept_a}' 和 '{concept_b}' 合并到统一表达"