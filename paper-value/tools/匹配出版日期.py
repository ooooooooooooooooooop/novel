import duckdb
import glob
import os
from pathlib import Path
from multiprocessing import Pool, cpu_count
from tqdm import tqdm  # pip install tqdm

_ROOT = Path(__file__).resolve().parent
if _ROOT.name == "tools":
    _ROOT = _ROOT.parent
JSON_DIR = r"C:/Desktop/新建文件夹/patch_add_date/"
PARQUET_DIR = r"C:/Desktop/新建文件夹/patch_add_date/parquet/"
os.makedirs(PARQUET_DIR, exist_ok=True)


# --------------------------
# 单文件 JSON → Parquet 转换函数
# --------------------------
def convert_one_json(json_path):
    parquet_path = PARQUET_DIR + os.path.basename(json_path).replace(".json", ".parquet")

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT keyid, pub_date
            FROM read_json('{json_path}', format='newline_delimited')
        ) TO '{parquet_path}' (FORMAT PARQUET);
    """)
    con.close()

    return parquet_path


# --------------------------
# 主流程：并行批处理 + 进度条
# --------------------------
if __name__ == "__main__":
    json_files = glob.glob(JSON_DIR + "*.json")

    print(f"发现 {len(json_files)} 个 JSON 文件，开始并行转换...")

    with Pool(processes=cpu_count()) as pool:
        parquet_files = list(
            tqdm(pool.imap(convert_one_json, json_files), total=len(json_files))
        )

    print("所有 JSON 已成功转为 Parquet！")

    # --------------------------
    # JOIN CSV 和 Parquet
    # --------------------------
    con = duckdb.connect()
    parquet_pattern = PARQUET_DIR + "*.parquet"

    csv_path = _ROOT / "data" / "raw" / "2026外文论文2.csv"
    if not csv_path.exists():
        csv_path = _ROOT / "2026外文论文2.csv"
    out_path = _ROOT / "data" / "raw" / "2026外文论文2_带pub_date.csv"
    if not out_path.parent.exists():
        out_path = _ROOT / "2026外文论文2_带pub_date.csv"
    con.execute(f"""
        CREATE OR REPLACE TABLE csv_data AS
        SELECT *
        FROM read_csv_auto('{csv_path.as_posix()}');
    """)

    result = con.execute(f"""
        SELECT 
            csv_data.*,
            pub.pub_date
        FROM csv_data
        LEFT JOIN read_parquet('{parquet_pattern}') AS pub
        ON csv_data.id = pub.keyid;
    """).df()

    result.to_csv(str(out_path), index=False)
    print("最终匹配完成！")
