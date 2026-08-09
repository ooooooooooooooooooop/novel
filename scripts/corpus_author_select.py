"""候选作者筛选：为 Author Model 选出最适合的作者。

标准（对齐 V2 §11）：
1. 多部作品（训练 ≥2 部 + 隐藏 ≥1 部）——作品数越多越好
2. 文本量（每部 10 章 × 章长，总字符够建模）
3. 章长一致性（同作者章长变异小 → 作者有稳定节奏，风格可探测）
4. 对白密度差异（对白占比是风格指纹的强代理；若作者内部稳定、作者间差异大 → 可区分度高）
5. 题材一致性 vs 跨题材（两种画像都有价值，分别标注）

输出：novels/_corpus/author_candidates.md + 控制台排行表
用法：python scripts/corpus_author_select.py
"""
import json
import os
import sys
from collections import defaultdict

CORPUS = os.path.join("novels", "_corpus", "full_novel_data.json")
OUT = os.path.join("novels", "_corpus", "author_candidates.md")

TOPN = 40  # 参与排名的多部作者数


def dialogue_ratio(text: str) -> float:
    """对白占比：中文引号『“”』包围内容字符数 / 总字符数（风格指纹代理）"""
    in_q = False
    cnt = 0
    total = max(1, len(text))
    for ch in text:
        if ch in '“”"':
            in_q = not in_q
            continue
        if in_q:
            cnt += 1
    return cnt / total


def main() -> int:
    data = json.load(open(CORPUS, encoding="utf-8"))
    author_works = defaultdict(list)
    for rec in data:
        novel = rec.get("novel", "")
        # 作者解析
        m = None
        for marker in ("作者：", "作者:"):
            i = novel.find(marker)
            if i != -1:
                m = novel[i + len(marker):].strip()
                break
        if not m:
            continue
        author = m.rstrip('）)】】')
        chapters = rec.get("chapters", []) or []
        if len(chapters) < 3:
            continue
        lens = [len(c) for c in chapters]
        ratio = [dialogue_ratio(c) for c in chapters]
        author_works[author].append({
            "novel": novel,
            "n_ch": len(chapters),
            "total_chars": sum(lens),
            "avg_ch_len": sum(lens) / len(lens),
            "len_cv": (sum((x - sum(lens)/len(lens))**2 for x in lens) / len(lens)) ** 0.5 / (sum(lens)/len(lens) + 1e-9),
            "dialogue_mean": sum(ratio) / len(ratio),
            "dialogue_cv": (sum((x - sum(ratio)/len(ratio))**2 for x in ratio) / len(ratio)) ** 0.5 / (sum(ratio)/len(ratio) + 1e-9) if sum(ratio) else 1.0,
        })

    # 只取多部作者
    multi = {a: ws for a, ws in author_works.items() if len(ws) >= 2}

    # 打分：作品数(40%) + 总字符对数(20%) + 章长稳定(20%) + 作者内对白稳定(20%)
    scores = []
    for a, ws in multi.items():
        n = len(ws)
        total_chars = sum(w["total_chars"] for w in ws)
        len_cv_mean = sum(w["len_cv"] for w in ws) / n
        dial_cv_mean = sum(w["dialogue_cv"] for w in ws) / n
        # 作者间对白区分度：本作者对白均值 vs 全体对白均值的偏离
        all_dm = sum(w["dialogue_mean"] for w in ws) / n
        score = (
            0.40 * min(n / 11, 1.0)
            + 0.20 * min(total_chars / 2_500_000, 1.0)
            + 0.20 * max(0, 1 - len_cv_mean)
            + 0.20 * max(0, 1 - dial_cv_mean)
        )
        scores.append({
            "author": a, "n_works": n, "total_chars": total_chars,
            "avg_work_chars": total_chars / n,
            "len_cv": len_cv_mean, "dialogue_mean": all_dm, "dialogue_cv": dial_cv_mean,
            "score": round(score, 3), "works": ws,
        })

    scores.sort(key=lambda x: -x["score"])

    lines = [
        "# 候选作者筛选（Author Model 语料）",
        "",
        f"共 {len(multi)} 位多部作者；以下为综合评分 TOP {TOPN}（作品数40% + 总字符20% + 章长稳定20% + 对白稳定20%）。",
        "",
        "| 排名 | 作者 | 作品数 | 总字符 | 均作品字符 | 章长CV | 对白占比 | 对白CV | 得分 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(scores[:TOPN], 1):
        lines.append(
            f"| {i} | {s['author']} | {s['n_works']} | {s['total_chars']:,} | "
            f"{int(s['avg_work_chars']):,} | {s['len_cv']:.2f} | {s['dialogue_mean']:.2f} | "
            f"{s['dialogue_cv']:.2f} | {s['score']} |"
        )
    lines += ["", "### TOP15 作品清单", ""]
    for s in scores[:15]:
        lines.append(f"#### {s['author']}（得分 {s['score']}）")
        for w in s["works"]:
            lines.append(f"- {w['novel']} | {w['n_ch']}章 | {w['total_chars']:,}字符 | 对白{w['dialogue_mean']:.2f}")
        lines.append("")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OUT] {OUT}")
    print(f"\nTOP {TOPN} 排行：")
    for i, s in enumerate(scores[:TOPN], 1):
        print(f"  {i:2d}. {s['author']} | {s['n_works']}部 | {s['total_chars']:,}字符 | 对白{s['dialogue_mean']:.2f} | 得分{s['score']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
