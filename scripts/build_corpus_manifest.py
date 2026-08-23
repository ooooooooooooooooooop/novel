"""从本地语料目录生成中性 Calibration Manifest（WP2/WP3 实操构建工具）。

隐私安全规范：
- 真实书名、真实作者名、真实绝对路径一律只保存在本地 manifest（gitignored / 不入版本库）。
- 输出 JSON 中的 ID 均为中性代号（author_xxx, work_xxx, topic_xxx）。
- split 策略：每位作者前 N-1 部为 support，最后 1 部为 holdout。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import defaultdict

GENRE_MAP = {
    "仙侠": "xianxia",
    "奇幻": "fantasy",
    "历史": "history",
    "都市": "urban",
    "悬疑": "suspense",
    "科幻": "sci-fi",
    "游戏": "gaming",
    "二次元": "acg",
    "武侠": "wuxia",
    "军事": "military",
    "体育": "sports",
}


def build_manifest(corpus_root: pathlib.Path, max_topics: int = 4, authors_per_topic: int = 4, works_per_author: int = 3) -> dict:
    # 扫描目录
    genre_authors: dict[str, dict[str, list[pathlib.Path]]] = defaultdict(lambda: defaultdict(list))
    for f in corpus_root.rglob("*.txt"):
        if f.stat().st_size < 50000:  # 过滤过小文件
            continue
        author_dir = f.parent.name
        genre_dir = f.parent.parent.name
        # 解析 genre 关键词
        matched_genre = None
        for k, v in GENRE_MAP.items():
            if k in genre_dir or k in author_dir:
                matched_genre = v
                break
        if not matched_genre:
            continue
        genre_authors[matched_genre][author_dir].append(f)

    # 筛选合格题材与作者
    selected_topics = {}
    for g, auths in genre_authors.items():
        qualified_auths = {a: sorted(flist) for a, flist in auths.items() if len(flist) >= works_per_author}
        if len(qualified_auths) >= authors_per_topic:
            selected_topics[g] = qualified_auths

    if len(selected_topics) < max_topics:
        max_topics = len(selected_topics)

    # 选取前 max_topics 个题材
    manifest_authors = []
    aid_seq = 0
    for topic in sorted(selected_topics.keys())[:max_topics]:
        auths = selected_topics[topic]
        for author_name in sorted(auths.keys())[:authors_per_topic]:
            aid_seq += 1
            aid = f"author_{aid_seq:03d}"
            works = []
            file_list = auths[author_name][:works_per_author]
            for w_idx, fpath in enumerate(file_list, 1):
                wid = f"{aid}_w{w_idx}"
                split = "support" if w_idx < len(file_list) else "holdout"
                works.append({
                    "work_id": wid,
                    "split": split,
                    "txt": str(fpath.resolve()),
                    "txt_path": str(fpath.resolve()),
                    "file_size": fpath.stat().st_size,
                })
            manifest_authors.append({
                "author_id": aid,
                "topic_stratum": topic,
                "raw_author_hint": hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:12],
                "works": works,
            })

    return {
        "manifest_version": "observed_calibration_manifest_v1.0",
        "schema": "real_local_corpus",
        "total_authors": len(manifest_authors),
        "topics": sorted(list({a["topic_stratum"] for a in manifest_authors})),
        "authors": manifest_authors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成本地语料 Calibration Manifest")
    parser.add_argument("--corpus-root", default=r"D:\Download\网络小说20年精华合集：100多位大神作家代表作全收录(2)", help="语料根目录")
    parser.add_argument("--out", default=".taskflow/active/observed-decision-author-signature-v1/real_corpus_manifest.local.json", help="输出路径")
    parser.add_argument("--topics", type=int, default=3, help="题材数")
    parser.add_argument("--authors-per-topic", type=int, default=4, help="每题材作者数")
    parser.add_argument("--works-per-author", type=int, default=3, help="每作者作品数")
    args = parser.parse_args()

    root = pathlib.Path(args.corpus_root)
    if not root.exists():
        print(f"[ERROR] 语料目录不存在: {root}", file=sys.stderr)
        return 1

    manifest = build_manifest(
        root,
        max_topics=args.topics,
        authors_per_topic=args.authors_per_topic,
        works_per_author=args.works_per_author,
    )
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 成功生成 Manifest: {out_path} (共 {manifest['total_authors']} 位作者，{len(manifest['topics'])} 个题材)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
