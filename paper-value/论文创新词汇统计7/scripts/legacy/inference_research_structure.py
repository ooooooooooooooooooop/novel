"""
研究行为结构化抽取模型推理脚本

用于加载训练好的模型，对输入的论文句子进行结构化抽取，方便手动验证模型效果。

支持：
1. 单句输入（命令行参数）
2. 交互式输入
3. 文件批量处理（每行一个句子）
4. 输出结构化结果（Task, Object, Aspect, Context）
"""

import os
import json
import re
import torch
import argparse
from pathlib import Path
from transformers import T5ForConditionalGeneration, T5Tokenizer
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def load_model_and_tokenizer(model_path: str, device: str = None):
    """
    加载训练好的模型和tokenizer
    
    参数:
        model_path: 模型路径
        device: 设备（None表示自动选择）
    
    返回:
        model, tokenizer
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    logger.info(f"加载模型: {model_path}")
    logger.info(f"使用设备: {device}")
    
    tokenizer = T5Tokenizer.from_pretrained(model_path)
    model = T5ForConditionalGeneration.from_pretrained(model_path)
    model.to(device)
    model.eval()
    
    logger.info("模型加载完成")
    return model, tokenizer, device


def predict_single(model, tokenizer, sentence: str, device: str, 
                   max_input_length: int = 512, max_output_length: int = 128):
    """
    对单个句子进行预测
    
    参数:
        model: 模型
        tokenizer: tokenizer
        sentence: 输入句子
        device: 设备
        max_input_length: 输入最大长度
        max_output_length: 输出最大长度
    
    返回:
        结构化抽取结果字典
    """
    # 构建输入：extract: {sentence}
    input_text = f"extract: {sentence}"
    
    # Tokenize
    input_ids = tokenizer(
        input_text,
        max_length=max_input_length,
        padding='max_length',
        truncation=True,
        return_tensors='pt'
    ).to(device)
    
    # 生成预测
    with torch.no_grad():
        outputs = model.generate(
            input_ids=input_ids['input_ids'],
            attention_mask=input_ids['attention_mask'],
            max_length=max_output_length,
            num_beams=3,
            early_stopping=True,
            do_sample=False
        )
    
    # 解码
    decoded_output = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    # 解析JSON
    try:
        fields = json.loads(decoded_output)
        if not isinstance(fields, list) or len(fields) != 4:
            fields = [decoded_output, '', '', '']
    except (json.JSONDecodeError, ValueError):
        fields = [decoded_output, '', '', '']
    
    return {
        'sentence': sentence,
        'task': str(fields[0]) if len(fields) > 0 else '',
        'object': str(fields[1]) if len(fields) > 1 else '',
        'aspect': str(fields[2]) if len(fields) > 2 else '',
        'context': str(fields[3]) if len(fields) > 3 else '',
        'raw_output': decoded_output
    }


# 全局变量：spacy模型（懒加载）
_nlp = None

def split_into_sentences(text: str) -> list:
    """使用spacy小模型将文本分割成句子"""
    if not text or not text.strip():
        return []
    
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    
    doc = _nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    return sentences if sentences else [text.strip()]


def format_result(result: dict) -> tuple:
    """格式化输出结果：返回(完整行, 结果列表行)"""
    task = result['task'] if result['task'] not in ['null', 'nan', ''] else 'null'
    obj = result['object'] if result['object'] not in ['null', 'nan', ''] else 'null'
    aspect = result['aspect'] if result['aspect'] not in ['null', 'nan', ''] else 'null'
    context = result['context'] if result['context'] not in ['null', 'nan', ''] else 'null'
    result_list = [task, obj, aspect, context]
    
    # 检查是否全为空（包括null和nan）
    is_all_empty = all(x in ['null', 'nan', ''] for x in result_list)
    
    if is_all_empty:
        return None, None
    
    full_line = f"{result['sentence']}\t{result_list}"
    result_only_line = f"{result_list}"
    return full_line, result_only_line


def process_single_sentence(model, tokenizer, device: str, text: str, auto_split: bool = True):
    """
    处理单个句子或文本
    
    参数:
        model: 模型
        tokenizer: tokenizer
        device: 设备
        text: 输入文本（可能是单个句子或长文本）
        auto_split: 是否自动分句（如果文本较长）
    """
    # 如果启用自动分句且文本较长，进行分句
    if auto_split and len(text) > 200:  # 超过200字符认为可能是多句
        sentences = split_into_sentences(text)
        logger.info(f"检测到长文本，已分割为 {len(sentences)} 个句子")
        
        results = []
        full_lines = []
        result_only_lines = []
        
        for sentence in sentences:
            result = predict_single(model, tokenizer, sentence, device)
            results.append(result)
            full_line, result_only_line = format_result(result)
            if full_line:
                full_lines.append(full_line)
                result_only_lines.append(result_only_line)
        
        # 先打印所有完整行，再打印所有结果行
        for line in full_lines:
            print(line)
        for line in result_only_lines:
            print(line)
        
        return results
    else:
        # 单句处理
        result = predict_single(model, tokenizer, text, device)
        full_line, result_only_line = format_result(result)
        if full_line:
            print(full_line)
            print(result_only_line)
        return result


def process_file(model, tokenizer, device: str, input_file: str, output_file: str = None):
    """
    批量处理文件中的句子
    
    参数:
        model: 模型
        tokenizer: tokenizer
        device: 设备
        input_file: 输入文件（每行一个句子）
        output_file: 输出文件（可选，CSV格式）
    """
    logger.info(f"读取文件: {input_file}")
    
    results = []
    with open(input_file, 'r', encoding='utf-8') as f:
        sentences = [line.strip() for line in f if line.strip()]
    
    logger.info(f"共 {len(sentences)} 个句子")
    
    full_lines = []
    result_only_lines = []
    
    for sentence in sentences:
        result = predict_single(model, tokenizer, sentence, device)
        results.append(result)
        full_line, result_only_line = format_result(result)
        if full_line:
            full_lines.append(full_line)
            result_only_lines.append(result_only_line)
    
    # 先打印所有完整行，再打印所有结果行
    for line in full_lines:
        print(line)
    for line in result_only_lines:
        print(line)
    
    # 保存结果
    if output_file:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_file, index=False, encoding='utf-8')
        logger.info(f"结果已保存到: {output_file}")
    
    return results


def interactive_mode(model, tokenizer, device: str):
    """交互式模式"""
    print("\n" + "=" * 80)
    print("交互式推理模式")
    print("输入句子或文本进行结构化抽取，输入 'quit' 或 'exit' 退出")
    print("（长文本会自动分句处理）")
    print("=" * 80 + "\n")
    
    while True:
        try:
            text = input("请输入文本: ").strip()
            
            if not text:
                continue
            
            if text.lower() in ['quit', 'exit', 'q']:
                print("退出交互模式")
                break
            
            process_single_sentence(model, tokenizer, device, text, auto_split=True)
            print()
            
        except KeyboardInterrupt:
            print("\n退出交互模式")
            break
        except Exception as e:
            logger.error(f"处理出错: {e}")


if __name__ == "__main__":
    # ========== 配置变量（可直接修改） ==========
    MODEL_PATH = "./models/cached_models/research_structure_extractor"
    
    # 选择运行模式（三选一）：
    # 1. 单句模式：设置 SENTENCE 变量
    SENTENCE = """
OPTIMIZING CROP RECOMMENDATION SYSTEMS USING ADVANCED DEEP LEARNING TECHNIQUES	Agricultural;Bidirectional LSTM (BiLSTM);crop recommendation;Deep Learning (DL);Long Short-Term Memory (LSTM);Transformers	The agricultural sector plays a significant role in economic development, especially for developing nations, but farmers experience hurdles such as climate change interventions, soil management, and crop yield choices. To this end, this study turns to Deep Learning (DL) to solve these problems and develop a holistic approach that employs a range of DL approaches for crop selection based on soil condition, climate, and past farming records. Predicted models and methods: These are Long Short-Term Memory (LSTM), Bidirectional LSTM (BiLSTM), and Transformers;precision agriculture through crop prediction;data-driven decision-making on resource allocation to boost farm revenue;and soil management through the prediction of the soil pH and recommended crops. This plan of action is designed to help farmers make the most beneficial decision to enhance the farming results. © Little Lion Scientific.
 """
    
    # 2. 批量处理模式：设置 INPUT_FILE 变量
    INPUT_FILE = None  # 例如: "./test_sentences.txt"
    OUTPUT_FILE = None  # 例如: "./results.csv"
    
    # 3. 交互式模式：设置 INTERACTIVE = True
    INTERACTIVE = True  # True=交互式模式，False=使用命令行参数
    
    # 设备设置（None=自动选择）
    DEVICE = None  # "cuda" 或 "cpu" 或 None
    # ===========================================
    
    # 解析命令行参数（如果提供了命令行参数，会覆盖上面的变量）
    parser = argparse.ArgumentParser(description="研究行为结构化抽取模型推理")
    parser.add_argument("--model_path", type=str, default=MODEL_PATH)
    parser.add_argument("--sentence", type=str, default=SENTENCE)
    parser.add_argument("--input_file", type=str, default=INPUT_FILE)
    parser.add_argument("--output_file", type=str, default=OUTPUT_FILE)
    parser.add_argument("--interactive", action="store_true", default=INTERACTIVE)
    parser.add_argument("--device", type=str, default=DEVICE)
    
    args = parser.parse_args()
    
    # 使用命令行参数或变量配置
    model_path = args.model_path
    sentence = args.sentence
    input_file = args.input_file
    output_file = args.output_file
    interactive = args.interactive
    device = args.device
    
    # 检查模型路径
    model_path_obj = Path(model_path)
    if not model_path_obj.exists():
        logger.error(f"模型路径不存在: {model_path_obj}")
        logger.error("请先训练模型，或指定正确的模型路径")
        exit(1)
    
    # 加载模型
    model, tokenizer, device = load_model_and_tokenizer(str(model_path_obj), device)
    
    # 根据参数选择模式
    if sentence:
        # 单句模式（支持长文本自动分句）
        process_single_sentence(model, tokenizer, device, sentence, auto_split=True)
    elif input_file:
        # 批量处理模式
        if not Path(input_file).exists():
            logger.error(f"输入文件不存在: {input_file}")
            exit(1)
        process_file(model, tokenizer, device, input_file, output_file)
    elif interactive:
        # 交互式模式
        interactive_mode(model, tokenizer, device)
    else:
        # 默认交互式模式
        interactive_mode(model, tokenizer, device)
