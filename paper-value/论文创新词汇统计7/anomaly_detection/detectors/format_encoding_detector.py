"""
格式和编码检测器

检测数据格式和字符编码异常，包括字符编码问题、JSON/CSV格式错误、数据类型不匹配等。
"""

import json
import csv
import chardet
import codecs
import re
from typing import Dict, List, Any, Optional, Union, IO
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field
import io

from ..core.data_models import (
    Anomaly, AnomalySeverity, DetectionResult
)
from ..core.exceptions import DetectionLogicException
from ..core.logging import get_logger


@dataclass
class EncodingAnomaly(Anomaly):
    """字符编码异常"""
    file_path: str = ""
    detected_encoding: str = ""
    expected_encoding: str = ""
    confidence: float = 0.0
    problematic_bytes: List[str] = field(default_factory=list)
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, file_path: str = "", detected_encoding: str = "", 
                 expected_encoding: str = "", confidence: float = 0.0, 
                 problematic_bytes: List[str] = None, **kwargs):
        """初始化字符编码异常"""
        super().__init__(
            anomaly_type="encoding_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.file_path = file_path
        self.detected_encoding = detected_encoding
        self.expected_encoding = expected_encoding
        self.confidence = confidence
        self.problematic_bytes = problematic_bytes or []


@dataclass
class FormatAnomaly(Anomaly):
    """格式异常"""
    file_path: str = ""
    format_type: str = ""  # json, csv, etc.
    error_location: str = ""
    error_details: str = ""
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, file_path: str = "", format_type: str = "", 
                 error_location: str = "", error_details: str = "", **kwargs):
        """初始化格式异常"""
        super().__init__(
            anomaly_type="format_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.file_path = file_path
        self.format_type = format_type
        self.error_location = error_location
        self.error_details = error_details


@dataclass
class TypeMismatchAnomaly(Anomaly):
    """数据类型不匹配异常"""
    field_name: str = ""
    expected_type: str = ""
    actual_type: str = ""
    actual_value: Any = None
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, field_name: str = "", expected_type: str = "", 
                 actual_type: str = "", actual_value: Any = None, **kwargs):
        """初始化类型不匹配异常"""
        super().__init__(
            anomaly_type="type_mismatch_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.field_name = field_name
        self.expected_type = expected_type
        self.actual_type = actual_type
        self.actual_value = actual_value


@dataclass
class SpecialCharacterAnomaly(Anomaly):
    """特殊字符异常"""
    character: str = ""
    unicode_code: str = ""
    location: str = ""
    context: str = ""
    
    def __init__(self, severity: AnomalySeverity, description: str, affected_data: Dict[str, Any], 
                 suggested_fix: str, character: str = "", unicode_code: str = "", 
                 location: str = "", context: str = "", **kwargs):
        """初始化特殊字符异常"""
        super().__init__(
            anomaly_type="special_character_anomaly",
            severity=severity,
            description=description,
            affected_data=affected_data,
            suggested_fix=suggested_fix,
            **kwargs
        )
        self.character = character
        self.unicode_code = unicode_code
        self.location = location
        self.context = context


class FormatEncodingDetector:
    """格式和编码检测器
    
    检测数据格式和字符编码中的各类异常情况。
    """
    
    def __init__(self, config):
        """初始化格式编码检测器
        
        Args:
            config: 检测配置
        """
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
        
        # 检测阈值配置 - 从配置对象中读取，避免硬编码经验值
        self.encoding_confidence_threshold = getattr(config.thresholds, 'encoding_confidence_threshold', 0.8)
        self.max_special_chars_per_kb = getattr(config.thresholds, 'max_special_chars_per_kb', 10)
        
        # 预期的文件编码
        self.expected_encoding = getattr(config, 'expected_encoding', 'utf-8')
        
        # 危险特殊字符模式
        self.dangerous_patterns = [
            r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]',  # 控制字符
            r'[\uFFFE\uFFFF]',  # 非字符
            r'[\uD800-\uDFFF]',  # 代理对（单独出现时异常）
        ]
        
        # 常见的编码问题模式
        self.encoding_issue_patterns = [
            (r'â€™', "'", "Windows-1252编码的单引号在UTF-8中显示异常"),
            (r'â€œ', '"', "Windows-1252编码的左双引号在UTF-8中显示异常"),
            (r'â€\x9d', '"', "Windows-1252编码的右双引号在UTF-8中显示异常"),
            (r'Ã¡', 'á', "Latin-1编码的重音字符在UTF-8中显示异常"),
            (r'Ã©', 'é', "Latin-1编码的重音字符在UTF-8中显示异常"),
        ]
    
    def detect_encoding_anomalies(self, file_path: str) -> List[EncodingAnomaly]:
        """检测字符编码异常
        
        Args:
            file_path: 文件路径
            
        Returns:
            检测到的编码异常列表
        """
        anomalies = []
        
        try:
            # 读取文件的原始字节
            with open(file_path, 'rb') as f:
                raw_data = f.read()
            
            # 使用chardet检测编码
            detection_result = chardet.detect(raw_data)
            detected_encoding = detection_result.get('encoding', 'unknown')
            confidence = detection_result.get('confidence', 0.0)
            
            self.logger.debug(f"文件 {file_path} 检测到编码: {detected_encoding}, 置信度: {confidence}")
            
            # 检查编码置信度是否过低
            if confidence < self.encoding_confidence_threshold:
                anomaly = EncodingAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"文件编码检测置信度过低: {confidence:.2f}",
                    affected_data={
                        "file_path": file_path,
                        "detected_encoding": detected_encoding,
                        "confidence": confidence
                    },
                    suggested_fix=f"手动检查文件编码，或使用更可靠的编码检测方法",
                    file_path=file_path,
                    detected_encoding=detected_encoding,
                    expected_encoding=self.expected_encoding,
                    confidence=confidence
                )
                anomalies.append(anomaly)
            
            # 检查编码是否与预期不符
            if detected_encoding and detected_encoding.lower() != self.expected_encoding.lower():
                severity = AnomalySeverity.HIGH if confidence > 0.9 else AnomalySeverity.MEDIUM
                anomaly = EncodingAnomaly(
                    severity=severity,
                    description=f"文件编码与预期不符: 检测到 {detected_encoding}，预期 {self.expected_encoding}",
                    affected_data={
                        "file_path": file_path,
                        "detected_encoding": detected_encoding,
                        "expected_encoding": self.expected_encoding,
                        "confidence": confidence
                    },
                    suggested_fix=f"将文件转换为 {self.expected_encoding} 编码",
                    file_path=file_path,
                    detected_encoding=detected_encoding,
                    expected_encoding=self.expected_encoding,
                    confidence=confidence
                )
                anomalies.append(anomaly)
            
            # 尝试用预期编码读取文件，检查是否有解码错误
            try:
                with open(file_path, 'r', encoding=self.expected_encoding, errors='strict') as f:
                    content = f.read()
                    
                # 检查常见的编码问题模式
                problematic_patterns = self._check_encoding_patterns(content)
                if problematic_patterns:
                    anomaly = EncodingAnomaly(
                        severity=AnomalySeverity.HIGH,
                        description=f"发现编码问题模式: {len(problematic_patterns)} 个",
                        affected_data={
                            "file_path": file_path,
                            "patterns": problematic_patterns
                        },
                        suggested_fix="检查原始文件编码并重新转换",
                        file_path=file_path,
                        detected_encoding=detected_encoding,
                        expected_encoding=self.expected_encoding,
                        problematic_bytes=[p['pattern'] for p in problematic_patterns]
                    )
                    anomalies.append(anomaly)
                    
            except UnicodeDecodeError as e:
                anomaly = EncodingAnomaly(
                    severity=AnomalySeverity.CRITICAL,
                    description=f"使用 {self.expected_encoding} 编码读取文件失败: {str(e)}",
                    affected_data={
                        "file_path": file_path,
                        "error": str(e),
                        "position": e.start if hasattr(e, 'start') else None
                    },
                    suggested_fix=f"使用检测到的编码 {detected_encoding} 重新处理文件",
                    file_path=file_path,
                    detected_encoding=detected_encoding,
                    expected_encoding=self.expected_encoding
                )
                anomalies.append(anomaly)
                
        except Exception as e:
            self.logger.error(f"检测文件 {file_path} 编码时发生错误: {str(e)}")
            raise DetectionLogicException(f"编码检测失败: {str(e)}")
        
        return anomalies
    
    def detect_json_format_anomalies(self, file_path: str) -> List[FormatAnomaly]:
        """检测JSON格式异常
        
        Args:
            file_path: JSON文件路径
            
        Returns:
            检测到的格式异常列表
        """
        anomalies = []
        
        try:
            with open(file_path, 'r', encoding=self.expected_encoding) as f:
                content = f.read()
            
            # 尝试解析JSON
            try:
                json.loads(content)
                self.logger.debug(f"JSON文件 {file_path} 格式正常")
                
            except json.JSONDecodeError as e:
                # 分析JSON错误的具体位置和类型
                error_location = f"行 {e.lineno}, 列 {e.colno}" if hasattr(e, 'lineno') else "未知位置"
                
                # 尝试提供更详细的错误信息
                error_context = self._get_json_error_context(content, e)
                
                anomaly = FormatAnomaly(
                    severity=AnomalySeverity.HIGH,
                    description=f"JSON格式错误: {e.msg}",
                    affected_data={
                        "file_path": file_path,
                        "error_message": e.msg,
                        "error_location": error_location,
                        "error_context": error_context
                    },
                    suggested_fix=self._suggest_json_fix(e.msg),
                    file_path=file_path,
                    format_type="json",
                    error_location=error_location,
                    error_details=e.msg
                )
                anomalies.append(anomaly)
            
            # 检查JSON结构的合理性
            structure_anomalies = self._check_json_structure(content, file_path)
            anomalies.extend(structure_anomalies)
            
        except Exception as e:
            self.logger.error(f"检测JSON文件 {file_path} 时发生错误: {str(e)}")
            raise DetectionLogicException(f"JSON格式检测失败: {str(e)}")
        
        return anomalies
    
    def detect_csv_format_anomalies(self, file_path: str) -> List[FormatAnomaly]:
        """检测CSV格式异常
        
        Args:
            file_path: CSV文件路径
            
        Returns:
            检测到的格式异常列表
        """
        anomalies = []
        
        try:
            with open(file_path, 'r', encoding=self.expected_encoding) as f:
                # 尝试自动检测CSV方言
                sample = f.read(1024)
                f.seek(0)
                
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    self.logger.debug(f"CSV文件 {file_path} 检测到方言: delimiter='{dialect.delimiter}'")
                except csv.Error as e:
                    anomaly = FormatAnomaly(
                        severity=AnomalySeverity.MEDIUM,
                        description=f"无法检测CSV方言: {str(e)}",
                        affected_data={
                            "file_path": file_path,
                            "error": str(e),
                            "sample": sample[:100]
                        },
                        suggested_fix="手动指定CSV分隔符和格式参数",
                        file_path=file_path,
                        format_type="csv",
                        error_details=str(e)
                    )
                    anomalies.append(anomaly)
                    dialect = csv.excel  # 使用默认方言
                
                # 尝试读取CSV内容
                try:
                    reader = csv.reader(f, dialect=dialect)
                    rows = list(reader)
                    
                    # 检查CSV结构的一致性
                    structure_anomalies = self._check_csv_structure(rows, file_path)
                    anomalies.extend(structure_anomalies)
                    
                except csv.Error as e:
                    anomaly = FormatAnomaly(
                        severity=AnomalySeverity.HIGH,
                        description=f"CSV解析错误: {str(e)}",
                        affected_data={
                            "file_path": file_path,
                            "error": str(e)
                        },
                        suggested_fix="检查CSV文件格式，确保引号和分隔符正确",
                        file_path=file_path,
                        format_type="csv",
                        error_details=str(e)
                    )
                    anomalies.append(anomaly)
                    
        except Exception as e:
            self.logger.error(f"检测CSV文件 {file_path} 时发生错误: {str(e)}")
            raise DetectionLogicException(f"CSV格式检测失败: {str(e)}")
        
        return anomalies
    
    def detect_type_mismatches(self, data: Dict[str, Any], expected_schema: Dict[str, str]) -> List[TypeMismatchAnomaly]:
        """检测数据类型不匹配
        
        Args:
            data: 要检测的数据
            expected_schema: 预期的数据类型模式
            
        Returns:
            检测到的类型不匹配异常列表
        """
        anomalies = []
        
        for field_name, expected_type in expected_schema.items():
            if field_name not in data:
                continue
                
            actual_value = data[field_name]
            actual_type = type(actual_value).__name__
            
            # 检查类型是否匹配
            if not self._is_type_compatible(actual_value, expected_type):
                severity = self._get_type_mismatch_severity(expected_type, actual_type)
                
                anomaly = TypeMismatchAnomaly(
                    severity=severity,
                    description=f"字段 '{field_name}' 类型不匹配: 期望 {expected_type}，实际 {actual_type}",
                    affected_data={
                        "field_name": field_name,
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                        "actual_value": str(actual_value)[:100]  # 限制长度避免过长
                    },
                    suggested_fix=self._suggest_type_conversion(expected_type, actual_value),
                    field_name=field_name,
                    expected_type=expected_type,
                    actual_type=actual_type,
                    actual_value=actual_value
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def detect_special_characters(self, text: str, context: str = "") -> List[SpecialCharacterAnomaly]:
        """检测特殊字符异常
        
        Args:
            text: 要检测的文本
            context: 上下文信息
            
        Returns:
            检测到的特殊字符异常列表
        """
        anomalies = []
        
        # 检查危险的特殊字符
        for pattern in self.dangerous_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                char = match.group()
                position = match.start()
                
                # 获取字符的Unicode信息
                unicode_code = f"U+{ord(char):04X}" if len(char) == 1 else "复合字符"
                
                # 获取上下文
                start = max(0, position - 20)
                end = min(len(text), position + 20)
                char_context = text[start:end]
                
                anomaly = SpecialCharacterAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"发现危险特殊字符: {repr(char)} ({unicode_code})",
                    affected_data={
                        "character": char,
                        "unicode_code": unicode_code,
                        "position": position,
                        "context": context,
                        "surrounding_text": char_context
                    },
                    suggested_fix="移除或替换危险字符",
                    character=char,
                    unicode_code=unicode_code,
                    location=f"位置 {position}",
                    context=char_context
                )
                anomalies.append(anomaly)
        
        # 统计特殊字符密度
        special_char_count = sum(1 for char in text if ord(char) > 127)
        text_size_kb = len(text.encode('utf-8')) / 1024
        
        if text_size_kb > 0:
            special_char_density = special_char_count / text_size_kb
            
            if special_char_density > self.max_special_chars_per_kb:
                anomaly = SpecialCharacterAnomaly(
                    severity=AnomalySeverity.LOW,
                    description=f"特殊字符密度过高: {special_char_density:.1f} 个/KB",
                    affected_data={
                        "special_char_count": special_char_count,
                        "text_size_kb": text_size_kb,
                        "density": special_char_density,
                        "threshold": self.max_special_chars_per_kb,
                        "context": context
                    },
                    suggested_fix="检查文本内容是否包含过多非ASCII字符",
                    location=context,
                    context=f"密度: {special_char_density:.1f}/KB"
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _check_encoding_patterns(self, content: str) -> List[Dict[str, str]]:
        """检查常见的编码问题模式"""
        problems = []
        
        for pattern, correct, description in self.encoding_issue_patterns:
            matches = re.findall(pattern, content)
            if matches:
                problems.append({
                    "pattern": pattern,
                    "correct": correct,
                    "description": description,
                    "count": len(matches)
                })
        
        return problems
    
    def _get_json_error_context(self, content: str, error: json.JSONDecodeError) -> str:
        """获取JSON错误的上下文信息"""
        if not hasattr(error, 'pos'):
            return "无法确定错误位置"
        
        pos = error.pos
        start = max(0, pos - 50)
        end = min(len(content), pos + 50)
        
        context = content[start:end]
        marker_pos = pos - start
        
        return f"...{context[:marker_pos]}>>>{context[marker_pos]}<<<{context[marker_pos+1:]}..."
    
    def _suggest_json_fix(self, error_msg: str) -> str:
        """根据JSON错误信息提供修复建议"""
        suggestions = {
            "Expecting ',' delimiter": "检查对象或数组中是否缺少逗号分隔符",
            "Expecting ':' delimiter": "检查对象中键值对是否缺少冒号",
            "Expecting property name": "检查对象中是否有未加引号的属性名",
            "Unterminated string": "检查字符串是否缺少结束引号",
            "Invalid control character": "检查字符串中是否包含未转义的控制字符",
            "Extra data": "检查JSON末尾是否有多余的内容"
        }
        
        for pattern, suggestion in suggestions.items():
            if pattern.lower() in error_msg.lower():
                return suggestion
        
        return "检查JSON语法是否正确，使用JSON验证工具进行详细分析"
    
    def _check_json_structure(self, content: str, file_path: str) -> List[FormatAnomaly]:
        """检查JSON结构的合理性"""
        anomalies = []
        
        try:
            data = json.loads(content)
            
            # 检查是否为空对象或数组
            if isinstance(data, (dict, list)) and len(data) == 0:
                anomaly = FormatAnomaly(
                    severity=AnomalySeverity.LOW,
                    description="JSON文件为空",
                    affected_data={"file_path": file_path},
                    suggested_fix="确认文件是否应该包含数据",
                    file_path=file_path,
                    format_type="json",
                    error_details="空JSON结构"
                )
                anomalies.append(anomaly)
            
            # 检查嵌套深度
            max_depth = self._get_json_depth(data)
            if max_depth > 10:  # 这是经验值，应该在注释中说明
                anomaly = FormatAnomaly(
                    severity=AnomalySeverity.MEDIUM,
                    description=f"JSON嵌套层次过深: {max_depth} 层",
                    affected_data={
                        "file_path": file_path,
                        "depth": max_depth,
                        "threshold": 10  # 经验值：超过10层可能影响处理性能
                    },
                    suggested_fix="考虑简化JSON结构或分解为多个文件",
                    file_path=file_path,
                    format_type="json",
                    error_details=f"嵌套深度: {max_depth}"
                )
                anomalies.append(anomaly)
                
        except json.JSONDecodeError:
            # JSON解析错误已在上层处理
            pass
        
        return anomalies
    
    def _check_csv_structure(self, rows: List[List[str]], file_path: str) -> List[FormatAnomaly]:
        """检查CSV结构的一致性"""
        anomalies = []
        
        if not rows:
            anomaly = FormatAnomaly(
                severity=AnomalySeverity.MEDIUM,
                description="CSV文件为空",
                affected_data={"file_path": file_path},
                suggested_fix="确认文件是否应该包含数据",
                file_path=file_path,
                format_type="csv",
                error_details="空CSV文件"
            )
            anomalies.append(anomaly)
            return anomalies
        
        # 检查列数一致性
        header_cols = len(rows[0]) if rows else 0
        inconsistent_rows = []
        
        for i, row in enumerate(rows[1:], 1):  # 跳过标题行
            if len(row) != header_cols:
                inconsistent_rows.append({
                    "row_number": i + 1,
                    "expected_cols": header_cols,
                    "actual_cols": len(row)
                })
        
        if inconsistent_rows:
            anomaly = FormatAnomaly(
                severity=AnomalySeverity.HIGH,
                description=f"CSV列数不一致: {len(inconsistent_rows)} 行有问题",
                affected_data={
                    "file_path": file_path,
                    "expected_columns": header_cols,
                    "inconsistent_rows": inconsistent_rows[:10]  # 只显示前10个
                },
                suggested_fix="检查CSV文件中的分隔符和引号使用是否正确",
                file_path=file_path,
                format_type="csv",
                error_details=f"{len(inconsistent_rows)} 行列数不匹配"
            )
            anomalies.append(anomaly)
        
        return anomalies
    
    def _is_type_compatible(self, value: Any, expected_type: str) -> bool:
        """检查值是否与期望类型兼容"""
        type_checkers = {
            'str': lambda x: isinstance(x, str),
            'int': lambda x: isinstance(x, int) or (isinstance(x, str) and x.isdigit()),
            'float': lambda x: isinstance(x, (int, float)) or (isinstance(x, str) and self._is_numeric(x)),
            'bool': lambda x: isinstance(x, bool) or (isinstance(x, str) and x.lower() in ('true', 'false', '1', '0')),
            'list': lambda x: isinstance(x, list),
            'dict': lambda x: isinstance(x, dict),
            'datetime': lambda x: isinstance(x, datetime) or (isinstance(x, str) and self._is_datetime_string(x))
        }
        
        checker = type_checkers.get(expected_type.lower())
        return checker(value) if checker else False
    
    def _is_numeric(self, value: str) -> bool:
        """检查字符串是否为数值"""
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    def _is_datetime_string(self, value: str) -> bool:
        """检查字符串是否为日期时间格式"""
        datetime_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',  # YYYY-MM-DD HH:MM:SS
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',  # ISO format
        ]
        
        return any(re.match(pattern, value) for pattern in datetime_patterns)
    
    def _get_type_mismatch_severity(self, expected_type: str, actual_type: str) -> AnomalySeverity:
        """根据类型不匹配情况确定严重性"""
        # 数值类型之间的转换通常不太严重
        numeric_types = {'int', 'float', 'str'}
        if expected_type in numeric_types and actual_type in numeric_types:
            return AnomalySeverity.LOW
        
        # 字符串可以转换为大多数类型
        if actual_type == 'str':
            return AnomalySeverity.MEDIUM
        
        # 其他类型不匹配比较严重
        return AnomalySeverity.HIGH
    
    def _suggest_type_conversion(self, expected_type: str, actual_value: Any) -> str:
        """提供类型转换建议"""
        suggestions = {
            'int': f"使用 int({repr(actual_value)}) 转换为整数",
            'float': f"使用 float({repr(actual_value)}) 转换为浮点数",
            'str': f"使用 str({repr(actual_value)}) 转换为字符串",
            'bool': f"使用 bool({repr(actual_value)}) 转换为布尔值",
            'list': f"将 {repr(actual_value)} 包装为列表: [{repr(actual_value)}]",
            'dict': "检查数据结构，确保为字典格式"
        }
        
        return suggestions.get(expected_type, f"将数据转换为 {expected_type} 类型")
    
    def _get_json_depth(self, obj: Any, current_depth: int = 0) -> int:
        """计算JSON对象的嵌套深度"""
        if isinstance(obj, dict):
            if not obj:
                return current_depth
            return max(self._get_json_depth(value, current_depth + 1) for value in obj.values())
        elif isinstance(obj, list):
            if not obj:
                return current_depth
            return max(self._get_json_depth(item, current_depth + 1) for item in obj)
        else:
            return current_depth
    
    def get_detector_name(self) -> str:
        """获取检测器名称"""
        return "FormatEncodingDetector"
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的数据类型"""
        return ["file", "json", "csv", "text", "encoding"]