# -*- coding: utf-8 -*-
"""单篇论文创新度查询示例：按标题片段查找并输出分数与同年百分位。"""
import os
import sys
import json
import sqlite3
import numpy as np
from pathlib import Path

BASE = str(Path(__file__).resolve().parents[2])
if BASE not in sys.path:
    sys.path.insert(0, BASE)
from project_config import load_project_config, get_paths

_cfg = load_project_config()
_paths = get_paths(_cfg)
DB_PATH = _paths["rpu_db_path"]
OUTPUT_DIR = _paths["innovation_output_dir"]

# 本例：中国教育应急管理（新冠停课不停学），此前已知高分
EXAMPLE_TITLE_FRAGMENT = "Suspending Classes Without Stopping Learning"


def main():
    if not os.path.exists(DB_PATH):
        print("DB not found:", DB_PATH)
        return
    if not os.path.isdir(OUTPUT_DIR):
        print("Output dir not found:", OUTPUT_DIR)
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT paper_id, title, pub_year FROM papers WHERE title LIKE ? LIMIT 5",
        ("%" + EXAMPLE_TITLE_FRAGMENT + "%",),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No paper found for title fragment:", repr(EXAMPLE_TITLE_FRAGMENT))
        return

    # 取第一篇
    paper_id, title, pub_year = rows[0]
    year = int(pub_year) if pub_year else None
    path = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
    if not os.path.exists(path):
        print("No innovation file for year", year)
        return

    # 流式查找该 paper_id 的记录
    rec = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("paper_id") == paper_id:
                rec = r
                break

    if not rec:
        print("Paper not in innovation jsonl for year", year)
        return

    # 同年分布用于百分位
    scores = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            scores.append(json.loads(line).get("total_score_v2") or 0)
    arr = np.array(scores)
    score = rec.get("total_score_v2") or 0
    pct = float(np.sum(arr <= score) / len(arr) * 100)
    p70 = float(np.percentile(arr, 70))

    print("Example:", EXAMPLE_TITLE_FRAGMENT)
    print("=" * 60)
    print("paper_id:", paper_id)
    print("title:", (title or "")[:90] + ("..." if len(title or "") > 90 else ""))
    print("pub_year:", pub_year)
    print("-" * 60)
    print("total_score_v2:", score)
    print("Same-year percentile: above ~{:.1f}% of {} papers".format(pct, year))
    print("Above P70 (high):", "yes" if score >= p70 else "no", "(P70={:.2f})".format(p70))
    print("-" * 60)
    print("s_peak:", rec.get("s_peak"), "  s_synergy:", rec.get("s_synergy"), "  s_bonus:", rec.get("s_bonus"), "  score_v2:", rec.get("score_v2"))
    print("peak_trigger:", rec.get("peak_trigger"))
    print("synergy_trigger:", rec.get("synergy_trigger"))
    print("bonus_trigger:", rec.get("bonus_trigger"))


if __name__ == "__main__":
    main()
