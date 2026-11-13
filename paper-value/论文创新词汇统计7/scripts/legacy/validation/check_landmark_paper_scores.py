# -*- coding: utf-8 -*-
"""
检测「提出新冠」与「提出人工智能」的代表性论文是否获得高创新度分数。

针对的是开创性论文（首次报告/提出概念的少数文献），而非该主题下全部论文。
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


# 提出新冠：仅首报/命名级标题片段（避免宽词如 SARS-CoV-2 命中数万篇导致超时）
COVID_LANDMARK_TITLES = [
    "new coronavirus associated with human respiratory disease in China",
    "novel coronavirus outbreak of global health concern",
    "Clinical features of patients infected with 2019 novel coronavirus",
    "Genomic characterisation of 2019 novel coronavirus",
    "Genomic characterization of 2019 novel coronavirus",
    "A novel coronavirus from patients with pneumonia in China",
    "Early Transmission Dynamics in Wuhan",
    "Wuhan seafood market",
    "pneumonia of unknown etiology",
]
COVID_MAX_PRINT = 25

# 提出（现代）人工智能/深度学习：短关键词 + 完整片段（便于命中 AlexNet / GAN 等）
AI_LANDMARK_TITLES = [
    "ImageNet",
    "ImageNet Classification with Deep Convolutional",
    "ImageNet classification with deep convolutional",
    "Deep Convolutional Neural Networks",
    "Generative Adversarial Networks",
    "Generative Adversarial networks",
    "Generative Adversarial",
]
AI_MAX_PRINT = 40


def load_scores_for_year(year: int) -> dict:
    path = os.path.join(OUTPUT_DIR, f"innovation_v2_{year}.jsonl")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            out[rec["paper_id"]] = rec
    return out


def percentile_of_score(all_scores: np.ndarray, score: float) -> float:
    """分数在同年中的百分位 (0-100)，越高表示越靠前。"""
    if len(all_scores) == 0:
        return 0.0
    return float(np.sum(all_scores <= score) / len(all_scores) * 100.0)


def find_papers_by_title_fragments(conn, fragments: list, years: list) -> list:
    """标题包含任一 fragment 的论文，返回 (paper_id, title, pub_year)。"""
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in years)
    rows = []
    for frag in fragments:
        cur.execute(
            f"""
            SELECT paper_id, title, pub_year FROM papers
            WHERE pub_year IN ({placeholders}) AND title LIKE ?
            ORDER BY pub_year, paper_id
            """,
            years + [f"%{frag}%"],
        )
        rows.extend(cur.fetchall())
    seen = set()
    unique = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            unique.append(r)
    return unique


def safe_str(s, max_len=80):
    if not s:
        return ""
    s = (s[:max_len] + ("..." if len(s) > max_len else "")).strip()
    enc = sys.stdout.encoding or "utf-8"
    try:
        return s.encode(enc, errors="replace").decode(enc, errors="replace")
    except (UnicodeDecodeError, LookupError):
        return s.encode("utf-8", errors="replace").decode("ascii", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="检测里程碑论文创新度分数")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径（JSON）")
    args = parser.parse_args()
    apply_config(args.config)

    if not os.path.exists(DB_PATH):
        print("数据库不存在:", DB_PATH)
        return
    if not os.path.isdir(OUTPUT_DIR):
        print("创新度输出目录不存在:", OUTPUT_DIR)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ----- 一、提出新冠的代表性论文（2020） -----
    print("=" * 72)
    print("一、提出新冠的代表性论文（首次报告/命名 2019-nCoV / SARS-CoV-2）")
    print("=" * 72)

    covid_papers = find_papers_by_title_fragments(conn, COVID_LANDMARK_TITLES, [2020])
    if not covid_papers:
        print("未在数据库中匹配到上述标题片段的论文（可能标题与库中略有差异）。")
    else:
        print(f"命中 {len(covid_papers)} 篇（仅展示首报级标题片段）。")
        scores_2020 = load_scores_for_year(2020)
        all_scores_2020 = np.array([r.get("total_score_v2") or 0 for r in scores_2020.values()])
        covid_with_score = []
        for row in covid_papers:
            pid, title, year = row[0], row[1], row[2]
            rec = scores_2020.get(pid)
            score = (rec.get("total_score_v2") or 0) if rec else None
            if score is not None:
                pct = percentile_of_score(all_scores_2020, score)
                p70 = float(np.percentile(all_scores_2020, 70))
                covid_with_score.append((pid, title, score, pct, p70))
            else:
                covid_with_score.append((pid, title, None, None, float(np.percentile(all_scores_2020, 70))))
        for i, (pid, title, score, pct, p70) in enumerate(covid_with_score[:COVID_MAX_PRINT]):
            if score is not None:
                high = "是" if score >= p70 else "否"
                print(f"\n  [{i+1}] 标题: {safe_str(title)}")
                print(f"      paper_id: {pid} | 总分: {score:.2f} | 百分位: {pct:.1f}% | 达P70: {high}")
            else:
                print(f"\n  [{i+1}] 标题: {safe_str(title)} | paper_id: {pid} (无分数)")
        if len(covid_with_score) > COVID_MAX_PRINT:
            print(f"\n  ... 共 {len(covid_with_score)} 篇，仅展示前 {COVID_MAX_PRINT} 篇")

    # ----- 二、提出人工智能/深度学习的代表性论文（2012 AlexNet；2014 GAN） -----
    print("\n" + "=" * 72)
    print("二、提出（现代）人工智能/深度学习的代表性论文（AlexNet 2012；GAN 2014）")
    print("=" * 72)
    print("说明: 数据库为 2010–2025，故检测 2012 ImageNet、2014 GAN 等里程碑论文。")

    ai_papers = find_papers_by_title_fragments(conn, AI_LANDMARK_TITLES, [2012, 2013, 2014, 2015])
    if not ai_papers:
        print("未在数据库中匹配到上述标题片段的论文。")
    else:
        print(f"命中 {len(ai_papers)} 篇（ImageNet/Deep Convolutional/GAN 等），按分数排序展示前 {AI_MAX_PRINT} 篇。")
        scores_by_year = {}
        ai_with_score = []
        for row in ai_papers:
            pid, title, year = row[0], row[1], row[2]
            if year not in scores_by_year:
                scores_by_year[year] = load_scores_for_year(year)
            scores_y = scores_by_year[year]
            rec = scores_y.get(pid)
            score = (rec.get("total_score_v2") or 0) if rec else None
            if score is not None and scores_y:
                all_scores_y = np.array([r.get("total_score_v2") or 0 for r in scores_y.values()])
                pct = percentile_of_score(all_scores_y, score)
                p70 = float(np.percentile(all_scores_y, 70))
                ai_with_score.append((pid, title, year, score, pct, p70))
        ai_with_score.sort(key=lambda x: -x[3])
        for i, (pid, title, year, score, pct, p70) in enumerate(ai_with_score[:AI_MAX_PRINT]):
            high = "是" if score >= p70 else "否"
            print(f"\n  [{i+1}] {year} | 总分: {score:.2f} | 百分位: {pct:.1f}% | 达P70: {high}")
            print(f"      标题: {safe_str(title)}")
            print(f"      paper_id: {pid}")
        if len(ai_with_score) > AI_MAX_PRINT:
            print(f"\n  ... 共 {len(ai_with_score)} 篇，仅展示前 {AI_MAX_PRINT} 篇（按分数降序）")

    conn.close()
    print("\n完成。")


if __name__ == "__main__":
    main()
