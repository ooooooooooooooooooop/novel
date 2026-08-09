"""Author Model 语料抽取：从 webnovelbench 抽出选定作者的完整作品语料，预留隐藏作品。

选定作者（第一批，中性 ID，实际作者由分析者指定）：
- author_hl    11部  历史官场    —— 单题材画像，对齐目标作品
- author_xh    11部  仙侠/奇幻   —— 跨题材画像，证伪作者级 vs 作品级
- author_cfyj  11部  剑修仙侠    —— 留作跨作者消融
- author_ft    10部  历史官场    —— 留作跨作者消融

布局（全部 gitignored，novels/_corpus/）：
novels/_corpus/authors/<作者名>/<作品slug>/
    manifest.json          {author, work_title, sample_pos, n_chapters}
    chapter_01.txt ...    每章正文（含原标题行）

每作者预留 1 部隐藏作品（隐藏作品不进入 Author Model 训练，用于对照验证）：
- author_hl  隐藏：hidden_a
- author_xh  隐藏：hidden_b
- author_cfyj 隐藏：hidden_c
- author_ft  隐藏：hidden_d

用法：python scripts/corpus_extract_authors.py
"""
import json
import os
import re
import sys

CORPUS = os.path.join("novels", "_corpus", "full_novel_data.json")
OUT_ROOT = os.path.join("novels", "_corpus", "authors")

SELECTED = {
    "author_hl": {"hidden": "hidden_a"},
    "author_xh": {"hidden": "hidden_b"},
    "author_cfyj": {"hidden": "hidden_c"},
    "author_ft": {"hidden": "hidden_d"},
}


def slugify(title: str) -> str:
    """书名 → 中性 slug（保留汉字与数字，去符号）"""
    title = re.sub(r"[（(].*?[)）]", "", title)  # 去括号注释（校对版全本等）
    title = re.sub(r"[^\w一-鿿]+", "", title)
    return title[:20]


def main() -> int:
    data = json.load(open(CORPUS, encoding="utf-8"))
    os.makedirs(OUT_ROOT, exist_ok=True)
    found = {a: [] for a in SELECTED}

    for rec in data:
        novel = rec.get("novel", "")
        for author in SELECTED:
            # 容忍「作者： X」等空白；作者名须独立成段（避免同名字作者误配）
            hit = False
            for marker in ("作者：", "作者:"):
                i = novel.find(marker)
                if i != -1:
                    name = novel[i + len(marker):].strip().rstrip("）)】】")
                    if name == author:
                        hit = True
                        break
            if not hit:
                continue
            chapters = rec.get("chapters", []) or []
            if not chapters:
                continue
            found[author].append({"novel": novel, "chapters": chapters})

    summary = []
    for author, cfg in SELECTED.items():
        works = found[author]
        hidden_title = cfg["hidden"]
        # 找出隐藏作品
        hidden = [w for w in works if hidden_title in w["novel"]]
        train = [w for w in works if hidden_title not in w["novel"]]
        if len(hidden) != 1:
            print(f"[WARN] {author}: 隐藏作品匹配 {len(hidden)} 个（期望1）")
            continue

        author_dir = os.path.join(OUT_ROOT, author)
        os.makedirs(author_dir, exist_ok=True)

        # 写训练作品
        train_meta = []
        for w in train:
            slug = slugify(w["novel"])
            wdir = os.path.join(author_dir, slug)
            os.makedirs(wdir, exist_ok=True)
            for i, ch in enumerate(w["chapters"], 1):
                with open(os.path.join(wdir, f"chapter_{i:03d}.txt"), "w", encoding="utf-8") as f:
                    f.write(ch)
            train_meta.append({
                "title": w["novel"], "slug": slug,
                "n_chapters": len(w["chapters"]),
                "total_chars": sum(len(c) for c in w["chapters"]),
                "hidden": False,
            })

        # 写隐藏作品
        h = hidden[0]
        hslug = slugify(h["novel"])
        hdir = os.path.join(author_dir, f"{hslug}__HIDDEN")
        os.makedirs(hdir, exist_ok=True)
        for i, ch in enumerate(h["chapters"], 1):
            with open(os.path.join(hdir, f"chapter_{i:03d}.txt"), "w", encoding="utf-8") as f:
                f.write(ch)
        hidden_meta = {
            "title": h["novel"], "slug": hslug,
            "n_chapters": len(h["chapters"]),
            "total_chars": sum(len(c) for c in h["chapters"]),
            "hidden": True,
        }

        manifest = {
            "author": author,
            "author_id": {"author_hl": "author_hl", "author_xh": "author_xh",
                          "author_cfyj": "author_cfyj", "author_ft": "author_ft"}[author],
            "n_works": len(train) + 1,
            "n_train": len(train),
            "train_works": train_meta,
            "hidden_work": hidden_meta,
        }
        with open(os.path.join(author_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)

        summary.append({
            "author": author, "n_train": len(train), "n_hidden": 1,
            "train_chars": sum(m["total_chars"] for m in train_meta),
            "hidden": hidden_meta["title"],
        })
        print(f"[OK] {author}: 训练{len(train)}部 {sum(m['total_chars'] for m in train_meta):,}字符 | 隐藏《{hidden_meta['title']}》")

    with open(os.path.join(OUT_ROOT, "manifest_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("[DONE] 语料抽取完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
