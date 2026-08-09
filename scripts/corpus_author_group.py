"""作者归组工具：从 webnovelbench full_novel_data.json 中按作者归组，统计每位作者的作品数与章节数。

输出（全部 gitignored，含完整小说信息，不提交 GitHub）：
- novels/_corpus/author_groups.json    {author: [{novel, n_chapters, total_chars}]}
- novels/_corpus/authors_multiwork.txt 同作者 >=2 部作品的作者清单（排序）
- novels/_corpus/corpus_stats.json     汇总统计

用法：python scripts/corpus_author_group.py
"""
import json
import os
import re
import sys
from collections import defaultdict

CORPUS = os.path.join("novels", "_corpus", "full_novel_data.json")
OUT_GROUPS = os.path.join("novels", "_corpus", "author_groups.json")
OUT_MULTI = os.path.join("novels", "_corpus", "authors_multiwork.txt")
OUT_STATS = os.path.join("novels", "_corpus", "corpus_stats.json")

# 作者名从 novel 字段解析：格式《书名》作者：作者名
AUTHOR_RE = re.compile(r"作者[：:]\s*([^》】\s]+)")


def parse_author(novel_str: str) -> str:
    m = AUTHOR_RE.search(novel_str)
    if m:
        return m.group(1).strip()
    # 兜底：尝试书名自身作为作者（失败标记）
    return novel_str[:20]


def main() -> int:
    if not os.path.exists(CORPUS):
        print(f"[FAIL] 语料未找到: {CORPUS}")
        return 1
    print(f"[INFO] 读取语料: {CORPUS}")
    with open(CORPUS, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[INFO] 作品总数: {len(data)}")

    # 按作者归组
    author_works = defaultdict(list)
    parse_fail = []
    for rec in data:
        novel_str = rec.get("novel", "")
        author = parse_author(novel_str)
        chapters = rec.get("chapters", []) or []
        total_chars = sum(len(c) for c in chapters)
        entry = {
            "novel": novel_str,
            "n_chapters": len(chapters),
            "total_chars": total_chars,
        }
        if author.startswith("《"):  # 未解析出作者
            parse_fail.append(novel_str)
        author_works[author].append(entry)

    # 排序：作品数降序、总章节降序
    sorted_authors = sorted(
        author_works.items(),
        key=lambda kv: (-len(kv[1]), -sum(w["n_chapters"] for w in kv[1])),
    )

    multi = {a: ws for a, ws in sorted_authors if len(ws) >= 2}
    print(f"[INFO] 作者总数: {len(author_works)}，同作者>=2部: {len(multi)}")
    print(f"[INFO] 解析失败(作者未识别): {len(parse_fail)}")

    # 写 author_groups.json
    with open(OUT_GROUPS, "w", encoding="utf-8") as f:
        json.dump(dict(sorted_authors), f, ensure_ascii=False, indent=1)
    print(f"[OUT] {OUT_GROUPS}")

    # 写 authors_multiwork.txt（多部作者 + 作品清单）
    lines = []
    for author, ws in multi.items():
        lines.append(f"== {author} | {len(ws)}部 | {sum(w['n_chapters'] for w in ws)}章 ==")
        for w in sorted(ws, key=lambda x: -x["n_chapters"]):
            lines.append(f"    {w['novel']} | {w['n_chapters']}章 | {w['total_chars']}字符")
    with open(OUT_MULTI, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OUT] {OUT_MULTI}")

    # 写 stats
    n_works = len(data)
    n_authors = len(author_works)
    n_multi_authors = len(multi)
    multi_items = list(multi.items()) if multi else []
    max_works_author = multi_items[0][0] if multi_items else None
    max_works = len(multi_items[0][1]) if multi_items else 0
    stats = {
        "n_works": n_works,
        "n_authors": n_authors,
        "n_multi_work_authors": n_multi_authors,
        "max_works_author": max_works_author,
        "max_works": max_works,
        "top20_multiwork_authors": [
            {"author": a, "n_works": len(ws), "n_chapters": sum(w["n_chapters"] for w in ws)}
            for a, ws in multi_items[:20]
        ],
    }
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(f"[OUT] {OUT_STATS}")
    print("[DONE] 归组完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
