"""
概念映射检测器

检测概念映射中的各类异常，包括大小写不一致、单复数冲突、数值范围异常和跨领域合并等。
"""

import re
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict, Counter
from datetime import datetime

from ..core.data_models import (
    CaseInconsistency, PluralSingularConflict, NumericalRangeAnomaly, 
    CrossDomainMerge, AnomalySeverity, DetectionResult
)
from ..core.exceptions import DetectionLogicException
from ..core.logging import get_logger
from ..data_access.mapping_file_manager import MappingFileManager


class ConceptMappingDetector:
    """概念映射检测器
    
    检测概念映射中的各类异常情况。
    """
    
    def __init__(self, config):
        """初始化概念映射检测器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取，避免硬编码经验值
        self.case_conflict_threshold = getattr(config.thresholds, 'case_similarity_threshold', 0.8)
        self.numerical_range_threshold = getattr(config.thresholds, 'numerical_range_threshold', 50.0)
        self.cross_domain_similarity_threshold = getattr(config.thresholds, 'cross_domain_threshold', 0.3)
        
        # 领域关键词（用于跨领域检测）
        self.domain_keywords = {
            'biology': ['gene', 'protein', 'cell', 'dna', 'rna', 'enzyme', 'tissue', 'organism', 'biological', 'genomic', 'genetic'],
            'chemistry': ['molecule', 'compound', 'reaction', 'catalyst', 'bond', 'element', 'acid', 'base', 'chemical', 'molecular'],
            'physics': ['particle', 'wave', 'energy', 'force', 'field', 'quantum', 'electron', 'photon', 'physical', 'mechanics'],
            'medicine': ['disease', 'treatment', 'therapy', 'drug', 'patient', 'clinical', 'diagnosis', 'symptom', 'medical', 'therapeutic'],
            'computer_science': ['algorithm', 'data', 'network', 'software', 'hardware', 'system', 'code', 'program', 'learning', 'neural', 'artificial', 'intelligence', 'computing', 'computational'],
            'mathematics': ['equation', 'function', 'matrix', 'theorem', 'proof', 'variable', 'formula', 'calculation', 'mathematical', 'statistical']
        }
        
        self.logger.info("概念映射检测器初始化完成")
    
    def detect_all_anomalies(self, mapping_manager: MappingFileManager) -> List[DetectionResult]:
        """检测所有概念映射异常
        
        Args:
            mapping_manager: 映射文件管理器
            
        Returns:
            检测结果列表
        """
        try:
            self.logger.info("开始概念映射异常检测")
            
            # 加载映射数据
            mappings = mapping_manager.load_mappings()
            
            all_results = []
            
            # 1. 大小写不一致检测
            case_results = self.detect_case_inconsistencies(mappings)
            all_results.extend(case_results)
            
            # 2. 单复数冲突检测
            plural_results = self.detect_plural_singular_conflicts(mappings)
            all_results.extend(plural_results)
            
            # 3. 数值范围异常检测
            numerical_results = self.detect_excessive_numerical_ranges(mappings)
            all_results.extend(numerical_results)
            
            # 4. 跨领域合并检测
            cross_domain_results = self.detect_cross_domain_merges(mappings)
            all_results.extend(cross_domain_results)
            
            self.logger.info(f"概念映射异常检测完成，发现 {len(all_results)} 个异常")
            
            return all_results
        
        except Exception as e:
            raise DetectionLogicException(f"概念映射异常检测失败: {e}",
                                        detector_name="ConceptMappingDetector")
    
    def detect_case_inconsistencies(self, mappings: Dict[str, str]) -> List[DetectionResult]:
        """检测大小写不一致异常
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            大小写不一致异常列表
        """
        try:
            self.logger.info("开始大小写不一致检测")
            
            results = []
            
            # 1. 创建大小写变体识别算法
            case_variants = self._identify_case_variants(mappings)
            
            # 2. 检测映射目标冲突
            target_conflicts = self._detect_mapping_target_conflicts(case_variants, mappings)
            
            # 3. 为每个冲突创建异常记录
            for conflict_group in target_conflicts:
                severity = self._assess_case_inconsistency_severity(conflict_group)
                
                anomaly = CaseInconsistency(
                    severity=severity,
                    description=self._generate_case_inconsistency_description(conflict_group),
                    affected_data={
                        'source_variants': conflict_group['variants'],
                        'target_conflicts': conflict_group['targets'],
                        'mapping_count': len(conflict_group['variants'])
                    },
                    suggested_fix=self._suggest_case_inconsistency_fix(conflict_group),
                    source_variants=conflict_group['variants'],
                    target_conflicts=conflict_group['targets']
                )
                
                result = DetectionResult(
                    anomaly_id=anomaly.anomaly_id,
                    detector_name="ConceptMappingDetector",
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    description=anomaly.description,
                    affected_entities=conflict_group['variants'],
                    evidence={
                        'case_variants': conflict_group['variants'],
                        'target_mappings': {v: mappings[v] for v in conflict_group['variants'] if v in mappings},
                        'conflict_type': 'case_inconsistency'
                    },
                    suggested_fixes=[anomaly.suggested_fix],
                    confidence_score=anomaly.confidence_score,
                    detection_timestamp=anomaly.timestamp
                )
                
                results.append(result)
            
            self.logger.info(f"大小写不一致检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"大小写不一致检测失败: {e}")
            raise
    
    def _identify_case_variants(self, mappings: Dict[str, str]) -> Dict[str, List[str]]:
        """识别大小写变体
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            大小写变体组，键为标准化形式，值为变体列表
        """
        case_groups = defaultdict(list)
        
        # 按小写形式分组
        for concept in mappings.keys():
            normalized = concept.lower().strip()
            if normalized:  # 跳过空字符串
                case_groups[normalized].append(concept)
        
        # 只保留有多个变体的组
        variants = {norm: variants for norm, variants in case_groups.items() 
                   if len(variants) > 1}
        
        self.logger.debug(f"识别出 {len(variants)} 个大小写变体组")
        
        return variants
    
    def _detect_mapping_target_conflicts(self, case_variants: Dict[str, List[str]], 
                                       mappings: Dict[str, str]) -> List[Dict[str, Any]]:
        """检测映射目标冲突
        
        Args:
            case_variants: 大小写变体组
            mappings: 概念映射数据
            
        Returns:
            冲突组列表
        """
        conflicts = []
        
        for normalized_form, variants in case_variants.items():
            # 获取每个变体的映射目标
            targets = {}
            for variant in variants:
                if variant in mappings:
                    target = mappings[variant]
                    if target not in targets:
                        targets[target] = []
                    targets[target].append(variant)
            
            # 如果有多个不同的目标，则存在冲突
            if len(targets) > 1:
                conflict = {
                    'normalized_form': normalized_form,
                    'variants': variants,
                    'targets': list(targets.keys()),
                    'target_mappings': targets
                }
                conflicts.append(conflict)
        
        return conflicts
    
    def _assess_case_inconsistency_severity(self, conflict_group: Dict[str, Any]) -> AnomalySeverity:
        """评估大小写不一致的严重性
        
        Args:
            conflict_group: 冲突组信息
            
        Returns:
            严重性级别
        """
        variant_count = len(conflict_group['variants'])
        target_count = len(conflict_group['targets'])
        
        # 基于变体数量和目标数量评估严重性
        if target_count >= 3 or variant_count >= 5:
            return AnomalySeverity.HIGH
        elif target_count == 2 and variant_count >= 3:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _generate_case_inconsistency_description(self, conflict_group: Dict[str, Any]) -> str:
        """生成大小写不一致异常的描述
        
        Args:
            conflict_group: 冲突组信息
            
        Returns:
            异常描述
        """
        variants = conflict_group['variants']
        targets = conflict_group['targets']
        
        return (f"发现大小写变体映射冲突: {len(variants)} 个变体 "
                f"({', '.join(variants[:3])}{'...' if len(variants) > 3 else ''}) "
                f"映射到 {len(targets)} 个不同目标 "
                f"({', '.join(targets[:2])}{'...' if len(targets) > 2 else ''})")
    
    def _suggest_case_inconsistency_fix(self, conflict_group: Dict[str, Any]) -> str:
        """为大小写不一致提供修复建议
        
        Args:
            conflict_group: 冲突组信息
            
        Returns:
            修复建议
        """
        targets = conflict_group['targets']
        target_mappings = conflict_group['target_mappings']
        
        # 找出最常见的目标作为推荐
        target_counts = {target: len(variants) for target, variants in target_mappings.items()}
        recommended_target = max(target_counts.keys(), key=lambda t: target_counts[t])
        
        return (f"建议将所有大小写变体统一映射到最常见的目标: '{recommended_target}' "
                f"(当前有 {target_counts[recommended_target]} 个变体映射到此目标)")
    
    def detect_plural_singular_conflicts(self, mappings: Dict[str, str]) -> List[DetectionResult]:
        """检测单复数冲突异常
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            单复数冲突异常列表
        """
        try:
            self.logger.info("开始单复数冲突检测")
            
            results = []
            
            # 识别单复数变体
            plural_groups = self._identify_plural_singular_pairs(mappings)
            
            # 检测冲突
            for group in plural_groups:
                if len(group['targets']) > 1:  # 存在冲突
                    severity = self._assess_plural_singular_severity(group)
                    
                    anomaly = PluralSingularConflict(
                        severity=severity,
                        description=self._generate_plural_singular_description(group),
                        affected_data={
                            'singular_forms': group.get('singular_forms', []),
                            'plural_forms': group.get('plural_forms', []),
                            'conflicting_targets': group['targets']
                        },
                        suggested_fix=self._suggest_plural_singular_fix(group),
                        singular_form=group.get('singular_forms', [''])[0] if group.get('singular_forms') else '',
                        plural_form=group.get('plural_forms', [''])[0] if group.get('plural_forms') else '',
                        conflicting_mappings=group['targets']
                    )
                    
                    result = DetectionResult(
                        anomaly_id=anomaly.anomaly_id,
                        detector_name="ConceptMappingDetector",
                        anomaly_type=anomaly.anomaly_type,
                        severity=anomaly.severity,
                        description=anomaly.description,
                        affected_entities=group.get('all_forms', []),
                        evidence={
                            'plural_singular_group': group,
                            'conflict_type': 'plural_singular_conflict'
                        },
                        suggested_fixes=[anomaly.suggested_fix],
                        confidence_score=anomaly.confidence_score,
                        detection_timestamp=anomaly.timestamp
                    )
                    
                    results.append(result)
            
            self.logger.info(f"单复数冲突检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"单复数冲突检测失败: {e}")
            raise
    
    def _identify_plural_singular_pairs(self, mappings: Dict[str, str]) -> List[Dict[str, Any]]:
        """识别单复数变体对
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            单复数组列表
        """
        groups = []
        processed = set()
        
        for concept in mappings.keys():
            if concept in processed:
                continue
            
            # 寻找可能的单复数对
            potential_pairs = self._find_plural_singular_candidates(concept, mappings.keys())
            
            if potential_pairs:
                # 分析这组概念的映射目标
                all_forms = [concept] + potential_pairs
                targets = {}
                
                for form in all_forms:
                    if form in mappings:
                        target = mappings[form]
                        if target not in targets:
                            targets[target] = []
                        targets[target].append(form)
                
                if len(targets) > 0:  # 至少有一个映射
                    group = {
                        'all_forms': all_forms,
                        'targets': list(targets.keys()),
                        'target_mappings': targets
                    }
                    
                    # 尝试区分单数和复数形式
                    singular_forms = []
                    plural_forms = []
                    
                    for form in all_forms:
                        if self._is_likely_plural(form):
                            plural_forms.append(form)
                        else:
                            singular_forms.append(form)
                    
                    group['singular_forms'] = singular_forms
                    group['plural_forms'] = plural_forms
                    
                    groups.append(group)
                
                # 标记为已处理
                processed.update(all_forms)
        
        return groups
    
    def _find_plural_singular_candidates(self, concept: str, all_concepts: Set[str]) -> List[str]:
        """寻找给定概念的单复数候选
        
        Args:
            concept: 目标概念
            all_concepts: 所有概念集合
            
        Returns:
            候选概念列表
        """
        candidates = []
        concept_lower = concept.lower()
        
        for other in all_concepts:
            if other == concept:
                continue
            
            other_lower = other.lower()
            
            # 简单的单复数规则检测
            if self._are_likely_plural_singular_pair(concept_lower, other_lower):
                candidates.append(other)
        
        return candidates
    
    def _are_likely_plural_singular_pair(self, word1: str, word2: str) -> bool:
        """判断两个词是否可能是单复数对
        
        Args:
            word1: 第一个词
            word2: 第二个词
            
        Returns:
            是否可能是单复数对
        """
        # 规则1: 简单的s结尾
        if (word1.endswith('s') and word1[:-1] == word2) or \
           (word2.endswith('s') and word2[:-1] == word1):
            return True
        
        # 规则2: es结尾
        if (word1.endswith('es') and word1[:-2] == word2) or \
           (word2.endswith('es') and word2[:-2] == word1):
            return True
        
        # 规则3: ies结尾 (y -> ies)
        if (word1.endswith('ies') and word1[:-3] + 'y' == word2) or \
           (word2.endswith('ies') and word2[:-3] + 'y' == word1):
            return True
        
        # 规则4: 不规则复数（扩展版本，涵盖更多科学术语）
        irregular_pairs = {
            # 常见不规则复数
            'child': 'children', 'mouse': 'mice', 'foot': 'feet',
            'tooth': 'teeth', 'goose': 'geese', 'man': 'men',
            'woman': 'women', 'person': 'people', 'ox': 'oxen',
            
            # 科学术语中的不规则复数
            'datum': 'data', 'phenomenon': 'phenomena', 'criterion': 'criteria',
            'bacterium': 'bacteria', 'medium': 'media', 'curriculum': 'curricula',
            'spectrum': 'spectra', 'nucleus': 'nuclei', 'radius': 'radii',
            'focus': 'foci', 'locus': 'loci', 'stimulus': 'stimuli',
            'analysis': 'analyses', 'basis': 'bases', 'crisis': 'crises',
            'diagnosis': 'diagnoses', 'hypothesis': 'hypotheses', 'synthesis': 'syntheses',
            'thesis': 'theses', 'axis': 'axes', 'matrix': 'matrices',
            'vertex': 'vertices', 'index': 'indices', 'appendix': 'appendices',
            
            # 生物医学术语
            'fungus': 'fungi', 'cactus': 'cacti', 'alumnus': 'alumni',
            'formula': 'formulae', 'larva': 'larvae', 'antenna': 'antennae'
        }
        
        for singular, plural in irregular_pairs.items():
            if (word1 == singular and word2 == plural) or \
               (word1 == plural and word2 == singular):
                return True
        
        return False
    
    def _is_likely_plural(self, word: str) -> bool:
        """判断词汇是否可能是复数形式
        
        Args:
            word: 词汇
            
        Returns:
            是否可能是复数
        """
        word_lower = word.lower()
        
        # 简单规则判断
        if word_lower.endswith(('s', 'es', 'ies')):
            return True
        
        # 不规则复数（扩展版本，与_are_likely_plural_singular_pair中的列表保持一致）
        irregular_plurals = {
            # 常见不规则复数
            'children', 'mice', 'feet', 'teeth', 'geese', 'men', 'women', 'people', 'oxen',
            
            # 科学术语中的不规则复数
            'data', 'phenomena', 'criteria', 'bacteria', 'media', 'curricula',
            'spectra', 'nuclei', 'radii', 'foci', 'loci', 'stimuli',
            'analyses', 'bases', 'crises', 'diagnoses', 'hypotheses', 'syntheses',
            'theses', 'axes', 'matrices', 'vertices', 'indices', 'appendices',
            
            # 生物医学术语
            'fungi', 'cacti', 'alumni', 'formulae', 'larvae', 'antennae'
        }
        if word_lower in irregular_plurals:
            return True
        
        return False
    
    def _assess_plural_singular_severity(self, group: Dict[str, Any]) -> AnomalySeverity:
        """评估单复数冲突的严重性"""
        target_count = len(group['targets'])
        form_count = len(group['all_forms'])
        
        if target_count >= 3 or form_count >= 4:
            return AnomalySeverity.HIGH
        elif target_count == 2 and form_count >= 3:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _generate_plural_singular_description(self, group: Dict[str, Any]) -> str:
        """生成单复数冲突异常的描述"""
        forms = group['all_forms']
        targets = group['targets']
        
        return (f"发现单复数形式映射冲突: {len(forms)} 个形式 "
                f"({', '.join(forms[:3])}{'...' if len(forms) > 3 else ''}) "
                f"映射到 {len(targets)} 个不同目标")
    
    def _suggest_plural_singular_fix(self, group: Dict[str, Any]) -> str:
        """为单复数冲突提供修复建议"""
        target_mappings = group['target_mappings']
        
        # 推荐映射到最常见的目标
        target_counts = {target: len(forms) for target, forms in target_mappings.items()}
        recommended_target = max(target_counts.keys(), key=lambda t: target_counts[t])
        
        return f"建议将所有单复数形式统一映射到: '{recommended_target}'"
    
    def detect_excessive_numerical_ranges(self, mappings: Dict[str, str]) -> List[DetectionResult]:
        """检测数值范围过大的异常合并
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            数值范围异常列表
        """
        try:
            self.logger.info("开始数值范围异常检测")
            
            results = []
            
            # 识别包含数值的概念
            numerical_concepts = self._identify_numerical_concepts(mappings)
            
            # 按目标分组
            target_groups = defaultdict(list)
            for concept, target in numerical_concepts.items():
                target_groups[target].append(concept)
            
            # 检测范围过大的合并
            for target, concepts in target_groups.items():
                if len(concepts) > 1:  # 多个概念映射到同一目标
                    range_info = self._analyze_numerical_range(concepts)
                    
                    if range_info and range_info['range_size'] > self.numerical_range_threshold:
                        severity = self._assess_numerical_range_severity(range_info)
                        
                        anomaly = NumericalRangeAnomaly(
                            severity=severity,
                            description=self._generate_numerical_range_description(target, range_info),
                            affected_data={
                                'target_concept': target,
                                'source_concepts': concepts,
                                'numerical_range': range_info
                            },
                            suggested_fix=self._suggest_numerical_range_fix(target, range_info),
                            min_value=range_info['min_value'],
                            max_value=range_info['max_value'],
                            range_size=range_info['range_size'],
                            threshold=self.numerical_range_threshold
                        )
                        
                        result = DetectionResult(
                            anomaly_id=anomaly.anomaly_id,
                            detector_name="ConceptMappingDetector",
                            anomaly_type=anomaly.anomaly_type,
                            severity=anomaly.severity,
                            description=anomaly.description,
                            affected_entities=concepts,
                            evidence={
                                'numerical_analysis': range_info,
                                'target_concept': target,
                                'conflict_type': 'numerical_range_anomaly'
                            },
                            suggested_fixes=[anomaly.suggested_fix],
                            confidence_score=anomaly.confidence_score,
                            detection_timestamp=anomaly.timestamp
                        )
                        
                        results.append(result)
            
            self.logger.info(f"数值范围异常检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"数值范围异常检测失败: {e}")
            raise
    
    def _identify_numerical_concepts(self, mappings: Dict[str, str]) -> Dict[str, str]:
        """识别包含数值的概念
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            包含数值的概念映射
        """
        numerical_concepts = {}
        
        for concept, target in mappings.items():
            # 检查概念中是否包含数字
            if re.search(r'\d', concept):
                numerical_concepts[concept] = target
        
        return numerical_concepts
    
    def _analyze_numerical_range(self, concepts: List[str]) -> Optional[Dict[str, Any]]:
        """分析概念中的数值范围
        
        Args:
            concepts: 概念列表
            
        Returns:
            数值范围分析结果
        """
        numbers = []
        
        for concept in concepts:
            # 提取概念中的所有数字
            concept_numbers = re.findall(r'\d+(?:\.\d+)?', concept)
            for num_str in concept_numbers:
                try:
                    numbers.append(float(num_str))
                except ValueError:
                    continue
        
        if len(numbers) < 2:
            return None
        
        min_val = min(numbers)
        max_val = max(numbers)
        range_size = max_val - min_val
        
        return {
            'min_value': min_val,
            'max_value': max_val,
            'range_size': range_size,
            'number_count': len(numbers),
            'unique_numbers': len(set(numbers)),
            'concepts_with_numbers': concepts
        }
    
    def _assess_numerical_range_severity(self, range_info: Dict[str, Any]) -> AnomalySeverity:
        """评估数值范围异常的严重性"""
        range_size = range_info['range_size']
        
        if range_size > 100:
            return AnomalySeverity.HIGH
        elif range_size > 50:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _generate_numerical_range_description(self, target: str, range_info: Dict[str, Any]) -> str:
        """生成数值范围异常的描述"""
        return (f"目标概念 '{target}' 合并了过大的数值范围: "
                f"{range_info['min_value']:.1f} - {range_info['max_value']:.1f} "
                f"(范围大小: {range_info['range_size']:.1f})")
    
    def _suggest_numerical_range_fix(self, target: str, range_info: Dict[str, Any]) -> str:
        """为数值范围异常提供修复建议"""
        return (f"建议将 '{target}' 按数值范围细分为多个子概念，"
                f"避免将差异过大的数值概念合并到同一目标")
    
    def detect_cross_domain_merges(self, mappings: Dict[str, str]) -> List[DetectionResult]:
        """检测跨领域错误合并
        
        Args:
            mappings: 概念映射数据
            
        Returns:
            跨领域合并异常列表
        """
        try:
            self.logger.info("开始跨领域合并检测")
            
            results = []
            
            # 按目标分组
            target_groups = defaultdict(list)
            for concept, target in mappings.items():
                target_groups[target].append(concept)
            
            # 检测跨领域合并
            for target, concepts in target_groups.items():
                if len(concepts) > 1:  # 多个概念映射到同一目标
                    domain_analysis = self._analyze_concept_domains(concepts)
                    
                    if self._is_cross_domain_merge(domain_analysis):
                        severity = self._assess_cross_domain_severity(domain_analysis)
                        
                        anomaly = CrossDomainMerge(
                            severity=severity,
                            description=self._generate_cross_domain_description(target, domain_analysis),
                            affected_data={
                                'target_concept': target,
                                'source_concepts': concepts,
                                'domain_analysis': domain_analysis
                            },
                            suggested_fix=self._suggest_cross_domain_fix(target, domain_analysis),
                            domain_a=domain_analysis.get('primary_domain', ''),
                            domain_b=domain_analysis.get('secondary_domain', ''),
                            similarity_score=domain_analysis.get('cross_domain_score', 0.0)
                        )
                        
                        result = DetectionResult(
                            anomaly_id=anomaly.anomaly_id,
                            detector_name="ConceptMappingDetector",
                            anomaly_type=anomaly.anomaly_type,
                            severity=anomaly.severity,
                            description=anomaly.description,
                            affected_entities=concepts,
                            evidence={
                                'domain_analysis': domain_analysis,
                                'target_concept': target,
                                'conflict_type': 'cross_domain_merge'
                            },
                            suggested_fixes=[anomaly.suggested_fix],
                            confidence_score=anomaly.confidence_score,
                            detection_timestamp=anomaly.timestamp
                        )
                        
                        results.append(result)
            
            self.logger.info(f"跨领域合并检测完成，发现 {len(results)} 个异常")
            
            return results
        
        except Exception as e:
            self.logger.error(f"跨领域合并检测失败: {e}")
            raise
    
    def _analyze_concept_domains(self, concepts: List[str]) -> Dict[str, Any]:
        """分析概念的领域归属
        
        Args:
            concepts: 概念列表
            
        Returns:
            领域分析结果
        """
        domain_scores = defaultdict(float)
        concept_domains = {}
        
        for concept in concepts:
            concept_lower = concept.lower()
            concept_domain_scores = {}
            
            # 计算每个领域的匹配分数
            for domain, keywords in self.domain_keywords.items():
                score = 0
                for keyword in keywords:
                    if keyword in concept_lower:
                        score += 1
                
                if score > 0:
                    concept_domain_scores[domain] = score
                    domain_scores[domain] += score
            
            # 确定概念的主要领域
            if concept_domain_scores:
                primary_domain = max(concept_domain_scores.keys(), 
                                   key=lambda d: concept_domain_scores[d])
                concept_domains[concept] = primary_domain
            else:
                concept_domains[concept] = 'unknown'
        
        # 分析整体领域分布
        domain_distribution = dict(domain_scores)
        sorted_domains = sorted(domain_distribution.items(), 
                              key=lambda x: x[1], reverse=True)
        
        analysis = {
            'concept_domains': concept_domains,
            'domain_distribution': domain_distribution,
            'sorted_domains': sorted_domains,
            'unique_domains': len([d for d in domain_distribution.values() if d > 0])
        }
        
        if len(sorted_domains) >= 2:
            analysis['primary_domain'] = sorted_domains[0][0]
            analysis['secondary_domain'] = sorted_domains[1][0]
            analysis['cross_domain_score'] = sorted_domains[1][1] / max(sorted_domains[0][1], 1)
        
        return analysis
    
    def _is_cross_domain_merge(self, domain_analysis: Dict[str, Any]) -> bool:
        """判断是否为跨领域合并
        
        Args:
            domain_analysis: 领域分析结果
            
        Returns:
            是否为跨领域合并
        """
        unique_domains = domain_analysis.get('unique_domains', 0)
        cross_domain_score = domain_analysis.get('cross_domain_score', 0.0)
        
        # 如果有多个领域且次要领域的分数足够高，则认为是跨领域合并
        return unique_domains >= 2 and cross_domain_score >= self.cross_domain_similarity_threshold
    
    def _assess_cross_domain_severity(self, domain_analysis: Dict[str, Any]) -> AnomalySeverity:
        """评估跨领域合并的严重性"""
        unique_domains = domain_analysis.get('unique_domains', 0)
        cross_domain_score = domain_analysis.get('cross_domain_score', 0.0)
        
        if unique_domains >= 3 or cross_domain_score >= 0.7:
            return AnomalySeverity.HIGH
        elif unique_domains == 2 and cross_domain_score >= 0.5:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW
    
    def _generate_cross_domain_description(self, target: str, domain_analysis: Dict[str, Any]) -> str:
        """生成跨领域合并异常的描述"""
        primary_domain = domain_analysis.get('primary_domain', 'unknown')
        secondary_domain = domain_analysis.get('secondary_domain', 'unknown')
        
        return (f"目标概念 '{target}' 错误合并了跨领域概念: "
                f"主要领域 '{primary_domain}' 和 '{secondary_domain}' 等")
    
    def _suggest_cross_domain_fix(self, target: str, domain_analysis: Dict[str, Any]) -> str:
        """为跨领域合并提供修复建议"""
        return (f"建议将 '{target}' 按领域分离，"
                f"避免将不同研究领域的概念合并到同一目标")