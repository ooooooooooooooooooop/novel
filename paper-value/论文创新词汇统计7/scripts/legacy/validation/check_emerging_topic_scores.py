# -*- coding: utf-8 -*-
"""
检测「新兴主题」论文（新冠、人工智能刚出现时）是否获得较高创新度分数。

用法: python check_emerging_topic_scores.py
"""

import os
import sys
import json
import sqlite3
import numpy as np
import argparse

from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths

def safe_str(s, max_len=70):
    if not s:
        return ""
    s = (s[:max_len] + ("..." if len(s) > max_len else "")).strip()
    enc = sys.stdout.encoding or "utf-8"
    try:
        return s.encode(enc, errors="replace").decode(enc, errors="replace")
    except (UnicodeDecodeError, LookupError):
        return s.encode("utf-8", errors="replace").decode("ascii", errors="replace")

_cfg = load_project_config()
_paths = get_paths(_cfg)
DB_PATH = _paths["rpu_db_path"]
OUTPUT_DIR = _paths["innovation_output_dir"]


def apply_config(config_path: str = None):
    global DB_PATH, OUTPUT_DIR
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    DB_PATH = paths["rpu_db_path"]
    OUTPUT_DIR = paths["innovation_output_dir"]


def load_scores_for_year(year: int) -> dict:
    """加载指定年份的 innovation 结果，返回 { paper_id: record }"""
    path = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            out[rec["paper_id"]] = rec
    return out


def year_baseline(scores_by_pid: dict) -> dict:
    """计算该年全体的均值、中位数、P70、P90"""
    vals = [r.get("total_score_v2") or 0 for r in scores_by_pid.values()]
    if not vals:
        return {"mean": 0, "median": 0, "p70": 0, "p90": 0, "n": 0}
    a = np.array(vals)
    return {
        "mean": float(np.mean(a)),
        "median": float(np.median(a)),
        "p70": float(np.percentile(a, 70)),
        "p90": float(np.percentile(a, 90)),
        "n": len(a),
    }


def find_papers_by_title_keywords(conn, keywords: list, years: list) -> list:
    """在 papers 表中按 title 包含任意 keyword 且 pub_year in years 查询。返回 (paper_id, title, pub_year)。"""
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in years)
    rows = []
    for kw in keywords:
        cur.execute(
            f"""
            SELECT paper_id, title, pub_year FROM papers
            WHERE pub_year IN ({placeholders}) AND title LIKE ?
            ORDER BY pub_year, paper_id
            """,
            years + [f"%{kw}%"],
        )
        rows.extend(cur.fetchall())
    seen = set()
    unique = []
    for r in rows:
        pid = r[0]
        if pid not in seen:
            seen.add(pid)
            unique.append(r)
    return unique


def main():
    parser = argparse.ArgumentParser(description="检测新兴主题论文的创新度表现")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()
    apply_config(args.config)

    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return
    if not os.path.isdir(OUTPUT_DIR):
        print(f"创新度输出目录不存在: {OUTPUT_DIR}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1) 新冠：2020–2021，标题含 COVID / coronavirus / SARS-CoV-2 / 新冠 等
    covid_keywords = ["COVID", "coronavirus", "SARS-CoV-2", "SARS-CoV", "新冠", "COVID-19", "Covid-19"]
    covid_years = [2020, 2021]
    covid_papers = find_papers_by_title_keywords(conn, covid_keywords, covid_years)
    print("=" * 70)
    print("一、新冠相关论文（2020–2021）")
    print("=" * 70)
    print(f"命中篇数: {len(covid_papers)}")

    covid_scores = []
    by_year = {y: [] for y in covid_years}
    for row in covid_papers:
        pid, title, year = row[0], row[1], row[2]
        by_year[year].append((pid, title))

    for y in covid_years:
        scores_dict = load_scores_for_year(y)
        baseline = year_baseline(scores_dict)
        print(f"\n{y} 年: 当年全量基线 — 均值={baseline['mean']:.2f}, 中位数={baseline['median']:.2f}, P70={baseline['p70']:.2f}, P90={baseline['p90']:.2f} (n={baseline['n']:,})")
        for pid, title in by_year[y]:
            rec = scores_dict.get(pid)
            if rec is None:
                continue
            s = rec.get("total_score_v2") or 0
            covid_scores.append((y, pid, title, s, baseline))
            above = "高于P70" if s >= baseline["p70"] else ("高于P90" if s >= baseline["p90"] else "未达P70")

    if covid_scores:
        arr = np.array([x[3] for x in covid_scores])
        print(f"\n新冠论文创新度: 均值={np.mean(arr):.2f}, 中位数={np.median(arr):.2f}, 最小={np.min(arr):.2f}, 最大={np.max(arr):.2f}")
        above_p70 = sum(1 for x in covid_scores if x[3] >= x[4]["p70"])
        above_p90 = sum(1 for x in covid_scores if x[3] >= x[4]["p90"])
        print(f"高于当年P70的比例: {above_p70}/{len(covid_scores)} ({100*above_p70/len(covid_scores):.1f}%)")
        print(f"高于当年P90的比例: {above_p90}/{len(covid_scores)} ({100*above_p90/len(covid_scores):.1f}%)")
        top = sorted(covid_scores, key=lambda x: x[3], reverse=True)[:5]
        print("\n创新度最高的 5 篇新冠相关论文:")
        for i, (yr, pid, title, sc, bl) in enumerate(top, 1):
            print(f"  {i}. [{sc:.2f}] {pid} | {safe_str(title or '')}")
    else:
        print("未在创新度结果中找到对应 paper_id，请确认 jsonl 与 DB 一致。")

    # 2) 人工智能/深度学习「刚出现」：2012–2014，标题含 deep learning / neural network / 深度学习 / 神经网络 / AI 等
    ai_keywords = [
        "deep learning", "neural network", "convolutional neural",
        "深度学习", "神经网络", "artificial intelligence", "machine learning",
    ]
    ai_years = [2012, 2013, 2014]
    ai_papers = find_papers_by_title_keywords(conn, ai_keywords, ai_years)
    print("\n" + "=" * 70)
    print("二、人工智能/深度学习相关论文（2012–2014，刚兴起期）")
    print("=" * 70)
    print(f"命中篇数: {len(ai_papers)}")

    ai_scores = []
    by_year_ai = {y: [] for y in ai_years}
    for row in ai_papers:
        pid, title, year = row[0], row[1], row[2]
        by_year_ai[year].append((pid, title))

    for y in ai_years:
        scores_dict = load_scores_for_year(y)
        baseline = year_baseline(scores_dict)
        print(f"\n{y} 年: 当年全量基线 — 均值={baseline['mean']:.2f}, 中位数={baseline['median']:.2f}, P70={baseline['p70']:.2f}, P90={baseline['p90']:.2f} (n={baseline['n']:,})")
        for pid, title in by_year_ai[y]:
            rec = scores_dict.get(pid)
            if rec is None:
                continue
            s = rec.get("total_score_v2") or 0
            ai_scores.append((y, pid, title, s, baseline))

    if ai_scores:
        arr = np.array([x[3] for x in ai_scores])
        print(f"\nAI/深度学习论文创新度: 均值={np.mean(arr):.2f}, 中位数={np.median(arr):.2f}, 最小={np.min(arr):.2f}, 最大={np.max(arr):.2f}")
        above_p70 = sum(1 for x in ai_scores if x[3] >= x[4]["p70"])
        above_p90 = sum(1 for x in ai_scores if x[3] >= x[4]["p90"])
        print(f"高于当年P70的比例: {above_p70}/{len(ai_scores)} ({100*above_p70/len(ai_scores):.1f}%)")
        print(f"高于当年P90的比例: {above_p90}/{len(ai_scores)} ({100*above_p90/len(ai_scores):.1f}%)")
        top = sorted(ai_scores, key=lambda x: x[3], reverse=True)[:5]
        print("\n创新度最高的 5 篇 AI/深度学习相关论文:")
        for i, (yr, pid, title, sc, bl) in enumerate(top, 1):
            print(f"  {i}. [{sc:.2f}] {pid} | {safe_str(title or '')}")
    else:
        print("未在创新度结果中找到对应 paper_id。")

    conn.close()
    print("\n完成。")


if __name__ == "__main__":
    main()
