# -*- coding: utf-8 -*-
"""
RPU 语义规范与丢弃规则模块

RPU (Research Process Unit) 四槽位语义边界定义：
- Task: 研究动作动词/动词短语（如 propose, evaluate, determine）
        排除：方法细节、具体技术名称
- Object: Task 直接作用的名词短语（被研究对象）
          排除：评价词、形容词短语
- Aspect: 研究维度/被研究部分（如 accuracy, efficiency, performance）
          排除：泛词、无具体指向的词
- Context: 条件/场景/应用（如 in this study, under X conditions）
           排除：其他非条件性修饰

丢弃规则（仅丢弃，不修补）：
- 规则 A：核心槽（Task 或 Object）为空 → 丢弃
- 规则 B：全槽位为空 → 丢弃（非研究句）
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class RPU:
    """Research Process Unit 数据结构"""
    sentence: str
    task: str
    object: str
    aspect: str
    context: str
    paper_id: str = ""
    
    def is_empty(self, field: str) -> bool:
        """检查字段是否为空"""
        value = getattr(self, field, "")
        return value in ("", "null", "nan", None)
    
    def to_dict(self) -> Dict:
        return {
            "paper_id": self.paper_id,
            "sentence": self.sentence,
            "task": self.task,
            "object": self.object,
            "aspect": self.aspect,
            "context": self.context
        }


def validate_rpu(rpu: RPU) -> Tuple[bool, str]:
    """
    验证 RPU 是否合法
    
    返回: (is_valid, discard_reason)
    - is_valid: True 表示保留，False 表示丢弃
    - discard_reason: 丢弃原因（如果 is_valid 为 False）
    """
    # 规则 B：全槽位为空 → 丢弃（非研究句）
    all_empty = (
        rpu.is_empty("task") and 
        rpu.is_empty("object") and 
        rpu.is_empty("aspect") and 
        rpu.is_empty("context")
    )
    if all_empty:
        return False, "all_slots_empty"
    
    # 规则 A：核心槽（Task 或 Object）为空 → 丢弃
    if rpu.is_empty("task") and rpu.is_empty("object"):
        return False, "core_slots_empty"
    
    # 通过验证
    return True, ""


def parse_model_output(sentence: str, raw_output: str, paper_id: str = "") -> Optional[RPU]:
    """
    解析模型输出为 RPU 对象
    
    参数:
        sentence: 原始句子
        raw_output: 模型输出的 JSON 字符串
        paper_id: 论文 ID
    
    返回:
        RPU 对象，解析失败返回 None
    """
    import json
    
    try:
        fields = json.loads(raw_output)
        if not isinstance(fields, list) or len(fields) != 4:
            return None
        
        def normalize(val):
            if val is None:
                return "null"
            val_str = str(val).strip()
            if val_str.lower() in ("", "null", "nan", "none"):
                return "null"
            return val_str
        
        return RPU(
            sentence=sentence,
            task=normalize(fields[0]),
            object=normalize(fields[1]),
            aspect=normalize(fields[2]),
            context=normalize(fields[3]),
            paper_id=paper_id
        )
    except (json.JSONDecodeError, ValueError, IndexError):
        return None


def filter_rpus(rpus: List[RPU]) -> Tuple[List[RPU], Dict[str, int]]:
    """
    过滤 RPU 列表，应用丢弃规则
    
    返回:
        (valid_rpus, discard_stats)
        - valid_rpus: 通过验证的 RPU 列表
        - discard_stats: 丢弃统计 {reason: count}
    """
    valid_rpus = []
    discard_stats = {
        "all_slots_empty": 0,
        "core_slots_empty": 0,
        "parse_error": 0
    }
    
    for rpu in rpus:
        if rpu is None:
            discard_stats["parse_error"] += 1
            continue
        
        is_valid, reason = validate_rpu(rpu)
        if is_valid:
            valid_rpus.append(rpu)
        else:
            discard_stats[reason] = discard_stats.get(reason, 0) + 1
    
    return valid_rpus, discard_stats
