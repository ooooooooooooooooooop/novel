# -*- coding: utf-8 -*-
"""
Script: supplement_paper_metadata.py
功能：独立补充论文元数据（年份、标题等）到数据库，支持并发写入
优势：不影响正在运行的 RPU 抽取任务

用法：
python supplement_paper_metadata.py
"""

import os
import csv
import sqlite3
import logging
import sys
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_config import load_project_config, get_paths

# ============================================================
# 配置
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_cfg = load_project_config()
_paths = get_paths(_cfg)


def _require_path(key: str) -> str:
    value = _paths.get(key)
    if value:
        return value
    raise KeyError(f"Missing required path key in project config: paths.{key}")


CONFIG = {
    "input_csv": _require_path("raw_papers_csv_path"),
    "db_path": _require_path("rpu_db_path"),
    "batch_size": 10000,
    "log_interval": 10000
}

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_db(conn):
    """初始化 papers 表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            pub_year INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

def process_metadata():
    if not os.path.exists(CONFIG["input_csv"]):
        logger.error(f"找不到输入文件: {CONFIG['input_csv']}")
        return

    logger.info(f"连接数据库: {CONFIG['db_path']}")
    # timeout 设置稍大，防止并发写入锁竞争
    conn = sqlite3.connect(CONFIG["db_path"], timeout=60)
    
    # 确保 WAL 模式开启（支持读写并发）
    conn.execute("PRAGMA journal_mode=WAL")
    
    init_db(conn)
    
    logger.info("开始扫描 CSV 并更新元数据...")
    
    batch_data = []
    count = 0
    updated_count = 0
    
    # 获取 CSV 总行数用于进度条
    total_lines = 0
    with open(CONFIG["input_csv"], 'r', encoding='utf-8') as f:
        for _ in f: total_lines += 1
    total_lines -= 1 # 减去 header
    
    with open(CONFIG["input_csv"], 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        pbar = tqdm(total=total_lines, desc="Updating Metadata")
        
        for row in reader:
            paper_id = row.get("id")
            title = row.get("title", "")
            pub_year = row.get("pub_year")
            
            if not paper_id:
                continue
                
            # 简单清洗年份
            try:
                if pub_year:
                    pub_year = int(float(pub_year)) # 处理 "2023.0" 这种格式
                else:
                    pub_year = None
            except:
                pub_year = None
            
            batch_data.append((paper_id, title, pub_year))
            count += 1
            
            if len(batch_data) >= CONFIG["batch_size"]:
                conn.executemany(
                    """INSERT OR IGNORE INTO papers (paper_id, title, pub_year) 
                       VALUES (?, ?, ?)""",
                    batch_data
                )
                conn.commit()
                updated_count += len(batch_data)
                batch_data = []
                pbar.update(CONFIG["batch_size"])
                
        # 处理剩余数据
        if batch_data:
            conn.executemany(
                """INSERT OR IGNORE INTO papers (paper_id, title, pub_year) 
                   VALUES (?, ?, ?)""",
                batch_data
            )
            conn.commit()
            updated_count += len(batch_data)
            pbar.update(len(batch_data))
            
        pbar.close()
    
    # 创建索引优化查询
    logger.info("创建索引...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_pub_year ON papers(pub_year)")
    conn.commit()
    
    conn.close()
    logger.info(f"完成！共处理 {count} 条记录，已存入数据库。")

if __name__ == "__main__":
    process_metadata()
