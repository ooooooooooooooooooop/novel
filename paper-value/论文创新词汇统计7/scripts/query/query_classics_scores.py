# -*- coding: utf-8 -*-
"""各学科经典/代表作：按标题片段在库中查找并输出创新度分数与同年百分位。每年 jsonl 只读一次。"""
import os
import json
import sqlite3
import numpy as np
from collections import defaultdict
from pathlib import Path

BASE = str(Path(__file__).resolve().parents[2])
import sys
if BASE not in sys.path:
    sys.path.insert(0, BASE)
from project_config import load_project_config, get_paths

_cfg = load_project_config()
_paths = get_paths(_cfg)
DB_PATH = _paths["rpu_db_path"]
OUTPUT_DIR = _paths["innovation_output_dir"]
IMPACT_DIR = _paths["impact_output_dir"]

# (学科, 标题片段, 论文概况, 原篇年)；原篇年=None 不限制年份；非空则仅该年视为原篇
CLASSICS = [
    ("物理/天文", "Gravitational Waves from a Binary Black Hole", "LIGO 引力波 (2016 原篇)", 2016),
    ("物理", "Observation of Higgs boson", "希格斯玻色子 (2012 原篇)", 2012),
    ("生物/基因编辑", "CRISPR-Cas9", "CRISPR 基因编辑 (取首篇)", None),
    ("生物", "Single-cell RNA-seq", "单细胞 RNA 测序 (取首篇)", None),
    ("计算机/AI", "ImageNet Classification with Deep Convolutional", "AlexNet/ImageNet (2012 原篇)", 2012),
    ("计算机/AI", "Generative Adversarial Networks", "GAN 原篇 (2014)", 2014),
    ("计算机/AI", "Mastering the game of Go with deep neural", "AlphaGo (2016 原篇)", 2016),
    ("医学", "PD-1 blockade", "PD-1/免疫检查点 (取首篇)", None),
    ("化学/材料", "Perovskite solar cell", "钙钛矿太阳能电池 (取首篇)", None),
    ("神经科学", "Optogenetics", "光遗传学 (2010 代表)", 2010),
]

# 公认创新论文：仅命中原篇年才计入
CONSENSUS_INNOVATION = [
    ("计算机/AI", "Attention is all you need", "Transformer 原篇 (2017)", 2017),
    ("计算机/AI", "Deep Residual Learning for Image Recognition", "ResNet 原篇 (2015)", 2015),
    ("计算机/AI", "BERT: Pre-training of Deep Bidirectional", "BERT 原篇 (2018)", 2018),
    ("医学/疫苗", "mRNA vaccine", "mRNA 疫苗 (取首篇)", None),
    ("医学/疫苗", "BNT162b2", "BNT162b2 疫苗原篇 (2020)", 2020),
    ("化学", "Metal-organic framework", "MOF (取首篇)", None),
    ("生物", "A programmable dual-RNA-guided DNA endonuclease", "CRISPR-Cas9 原篇 (2012)", 2012),
    ("物理", "Observation of a new particle", "希格斯 ATLAS/CMS (2012)", 2012),
    ("计算机/AI", "ImageNet classification with deep convolutional neural networks", "AlexNet 原篇 (2012)", 2012),
]
# 使用哪份列表：仅经典 / 仅公认创新 / 两者合并。均为 (学科, 片段, 概况, 原篇年)，原篇年非空时仅命中该年才计入
QUERY_LIST = CLASSICS + CONSENSUS_INNOVATION


def main():
    if not os.path.exists(DB_PATH):
        print("DB not found:", DB_PATH)
        return
    if not os.path.isdir(OUTPUT_DIR):
        print("Output dir not found:", OUTPUT_DIR)
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1) 查库：每个片段取一篇；若指定原篇年则仅命中该年，非原篇不放入结果
    found = []
    for discipline, frag, desc, origin_year in QUERY_LIST:
        if origin_year is not None:
            cur.execute(
                "SELECT paper_id, title, pub_year FROM papers WHERE title LIKE ? AND pub_year = ? ORDER BY paper_id LIMIT 1",
                ("%" + frag + "%", origin_year),
            )
        else:
            cur.execute(
                "SELECT paper_id, title, pub_year FROM papers WHERE title LIKE ? ORDER BY pub_year, paper_id LIMIT 1",
                ("%" + frag + "%",),
            )
        row = cur.fetchone()
        if row:
            found.append((discipline, frag, desc, row[0], row[1] or "", row[2]))
    conn.close()

    # 2) 按年份分组
    by_year = defaultdict(list)
    for discipline, frag, desc, paper_id, title, year in found:
        if year is not None:
            by_year[int(year)].append((discipline, frag, desc, paper_id, title))

    # 3) 每年只读一次 jsonl，取所需 paper 的 rec 和该年全部 score
    results = []
    for year in sorted(by_year.keys()):
        path = os.path.join(OUTPUT_DIR, "innovation_v2_{}.jsonl".format(year))
        if not os.path.exists(path):
            want_ids = {t[3] for t in by_year[year]}
            impact_by_pid = {}
            impact_path = os.path.join(IMPACT_DIR, "impact_final_{}.jsonl".format(year))
            if os.path.exists(impact_path):
                with open(impact_path, "r", encoding="utf-8") as f:
                    for line in f:
                        r = json.loads(line)
                        if r.get("paper_id") in want_ids:
                            impact_by_pid[r["paper_id"]] = (r.get("impact_score"), r.get("impact_role"))
            for t in by_year[year]:
                imp = impact_by_pid.get(t[3], (None, None))
                results.append((t[0], t[1], t[2], year, t[3], t[4], None, None, None, None, imp[0], imp[1]))
            continue
        want_ids = {t[3] for t in by_year[year]}
        recs = {}
        scores = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                scores.append(r.get("total_score_v2") or 0)
                if r.get("paper_id") in want_ids:
                    recs[r["paper_id"]] = r
        arr = np.array(scores) if scores else np.array([])
        p70 = float(np.percentile(arr, 70)) if len(arr) else 0
        impact_by_pid = {}
        impact_path = os.path.join(IMPACT_DIR, "impact_final_{}.jsonl".format(year))
        if os.path.exists(impact_path):
            with open(impact_path, "r", encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    pid = r.get("paper_id")
                    if pid in want_ids:
                        impact_by_pid[pid] = (r.get("impact_score"), r.get("impact_role"))
        for discipline, frag, desc, paper_id, title in by_year[year]:
            rec = recs.get(paper_id)
            imp = impact_by_pid.get(paper_id, (None, None))
            if rec is None:
                results.append((discipline, frag, desc, year, paper_id, title, None, None, None, None, imp[0], imp[1]))
                continue
            score = rec.get("total_score_v2") or 0
            pct = float(np.sum(arr <= score) / len(arr) * 100) if len(arr) else 0
            results.append((discipline, frag, desc, year, paper_id, title, score, pct, p70, rec, imp[0], imp[1]))

    # 4) 输出（含创新度 + 影响力）
    print("Discipline   | Year | Inno    | Pct(~)  | P70? | Impact  | Role    | 论文概况                | Title (abbrev)")
    print("-" * 130)
    for discipline, frag, desc, year, paper_id, title, score, pct, p70, rec, impact_score, impact_role in results:
        desc_short = (desc[:22] + "..") if len(desc) > 22 else desc
        imp_str = "{:.1f}".format(impact_score) if impact_score is not None else "-"
        role_str = (impact_role[:8] if impact_role else "-") if impact_role else "-"
        if score is None:
            print("{} | {} | (no inno) | {} | {}   | {} | {}".format(discipline[:11].ljust(11), year, imp_str.ljust(6), role_str.ljust(7), desc_short, title[:38]))
            continue
        high = "Y" if p70 and score >= p70 else "n"
        title_short = (title[:38] + "..") if len(title) > 38 else title
        print("{} | {} | {:7.2f} | ~{:5.1f}% | {}   | {} | {} | {} | {}".format(
            discipline[:11].ljust(11), year, score, pct, high, imp_str.ljust(6), role_str.ljust(7), desc_short.ljust(22), title_short))
    print("-" * 130)
    print("Inno=创新度(total_score_v2)  P70?=同年P70以上  Impact=影响力分数  Role=Pioneer/Ahead-of-time/Diffuser/Routine")

    # 5) 各项得分原因（基于 s_peak / s_synergy / s_bonus 与 trigger）
    print("\n" + "=" * 100)
    print("各项得分原因分析（基于抽取的 Task-Object 罕见度、篇内共现与修饰新颖度）")
    print("=" * 100)
    for discipline, frag, desc, year, paper_id, title, score, pct, p70, rec, impact_score, impact_role in results:
        if rec is None:
            continue
        sp = rec.get("s_peak") or 0
        ss = rec.get("s_synergy") or 0
        sb = rec.get("s_bonus") or 0
        pt = rec.get("peak_trigger") or "-"
        st = rec.get("synergy_trigger") or "-"
        bt = rec.get("bonus_trigger") or "-"
        if sp < 5 and ss < 5 and sb < 5:
            reason = "s_peak/s_synergy/s_bonus 均偏低 => 抽取到的(T,O)与篇内共现在本库历史中较常见，表述偏常规。"
        elif sp >= 10 or ss >= 10:
            reason = "s_peak 或 s_synergy 较高 => 文中存在在当年之前语料中罕见的(T,O)组合或篇内概念共现。"
        else:
            reason = "各信号中等 => 部分表述罕见、部分常见，综合得分居中。"
        imp_str = "impact={:.1f} role={}".format(impact_score, impact_role) if impact_score is not None else "impact=(无)"
        print("\n[{}] {} ({}年, 创新={:.2f}, {})".format(discipline, desc, year, score, imp_str))
        print("  s_peak={:.2f}  s_synergy={:.2f}  s_bonus={:.2f}".format(sp, ss, sb))
        print("  peak_trigger: {}  synergy: {}  bonus: {}".format(pt[:60] if len(str(pt)) > 60 else pt, st[:60] if len(str(st)) > 60 else st, bt[:60] if len(str(bt)) > 60 else bt))
        print("  原因: {}".format(reason))


if __name__ == "__main__":
    main()
