#!/usr/bin/env python3
"""Build the uncontaminated A1/G7 preference split manifest (v2).

为什么需要 v2：旧划分（split_manifest.json）的 tag_regex 是「小说|故事|童话|剧本|角色扮演」，
被用于 A1 前几轮的协议调参（阈值/位置偏置判定），已**污染**——不可再作为 G7 冻结 holdout
（G7 阈值 0.9 不得从污染数据上调整）。v2 从**同一原始基准**（m-a-p/Writing-Preference-Bench
中文子集）里选一个**从未出现在旧划分中的 prompt_id 集合**（文学非虚构类 tag），用与旧划分
完全相同的确定性分桶算法分桶，calibration 与 holdout 按 prompt_id 零交叉。

冻结不变式（本脚本以断言锁死，防漂移）：
- 来源：WP_bench_chinese.json，source_sha256 必须等于冻结值。
- 选择集：tag_regex 命中的 138 行（12 个 tag）。
- 分桶：uint32_be(sha256(utf8(prompt_id))[0:4]) mod 5（与旧划分同算法）。
- calibration = buckets [1,2,3,4] → 103 行 / 12 tag；holdout = bucket [0] → 35 行 / 8 tag。
- 零交叉：同一 prompt_id 的所有行只落一个划分；calibration 与 holdout 的 prompt_id
  集合互不相交；与旧划分（split_manifest.json）的 68 个 prompt_id 零交叉。

用法：python scripts/build_split_manifest_v2.py
产物：reference_texts/a1_benchmark/sources/writing_preference_bench/split_manifest_v2.json
（gitignored 本地冻结证据；本脚本幂等，重跑字节不变。）
"""

import hashlib
import json
import re
from pathlib import Path

BENCH_DIR = (
    Path(__file__).resolve().parents[1]
    / "reference_texts/a1_benchmark/sources/writing_preference_bench"
)
BENCH_PATH = BENCH_DIR / "WP_bench_chinese.json"
OLD_MANIFEST_PATH = BENCH_DIR / "split_manifest.json"
OUT_PATH = BENCH_DIR / "split_manifest_v2.json"

SOURCE_SHA256 = "fd9c8faf85b7f4ae4b48f938c9fd608e5ed2011f726789130b37c1588f2ab6e0"
DATASET = "m-a-p/Writing-Preference-Bench"
REVISION = "676d7114ce37ad5d8eff5b39f3648b855730bf77"
LICENSE = "apache-2.0"
SOURCE_FILE = "WP_bench_chinese.json"
FROZEN_AT = "2026-08-13"

TAG_REGEX = (
    r"散文|书评|影评|乐评|人物传记|悼词|旅行游记|博客文章|科普文章|诗歌|演讲稿|议论文|公开信|辩论稿"
)
ALGORITHM = "uint32_be(sha256(utf8(prompt_id))[0:4]) mod 5"
CALIB_BUCKETS = [1, 2, 3, 4]
HOLDOUT_BUCKETS = [0]

# 冻结时已验证的不变式值（2026-08-13 锁定）。
EXPECTED_LITA_ROWS = 138
EXPECTED_CALIB = 103
EXPECTED_CALIB_TAGS = 12
EXPECTED_HOLDOUT = 35
EXPECTED_HOLDOUT_TAGS = 8
EXPECTED_OLD_PIDS = 68


def sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bucket(pid: str) -> int:
    h = hashlib.sha256(pid.encode("utf-8")).digest()
    return int.from_bytes(h[0:4], "big") % 5


def load_old_prompt_ids() -> set[str]:
    """从旧划分 manifest 读其 prompt_id 集合（旧划分是本地冻结证据）。"""
    if not OLD_MANIFEST_PATH.exists():
        return set()
    data = json.loads(OLD_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    pids: set[str] = set()
    for key in ("calibration", "holdout"):
        for entry in data.get(key, []):
            pids.add(entry["prompt_id"])
    return pids


def main() -> None:
    assert sha256_hex(BENCH_PATH) == SOURCE_SHA256, "source bench hash mismatch"

    rows = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows

    tag_re = re.compile(TAG_REGEX)
    litA = [
        (index, row["prompt_id"], row["tag"])
        for index, row in enumerate(rows)
        if tag_re.search(row["tag"])
    ]
    assert len(litA) == EXPECTED_LITA_ROWS, f"litA rows {len(litA)}"

    # 同一 prompt_id 的所有行必须落同一 bucket（确定性保证）。
    pid_buckets: dict[str, set[int]] = {}
    for index, pid, tag in litA:
        pid_buckets.setdefault(pid, set()).add(bucket(pid))
    spanning = {p for p, bs in pid_buckets.items() if len(bs) > 1}
    assert not spanning, f"prompt_id spans multiple buckets: {sorted(spanning)}"

    calib_entries = [
        {"row_index": i, "prompt_id": pid, "tag": tag, "bucket": bucket(pid)}
        for i, pid, tag in litA
        if bucket(pid) in set(CALIB_BUCKETS)
    ]
    holdout_entries = [
        {"row_index": i, "prompt_id": pid, "tag": tag, "bucket": bucket(pid)}
        for i, pid, tag in litA
        if bucket(pid) in set(HOLDOUT_BUCKETS)
    ]
    calib_entries.sort(key=lambda e: e["row_index"])
    holdout_entries.sort(key=lambda e: e["row_index"])

    assert len(calib_entries) == EXPECTED_CALIB, f"calib {len(calib_entries)}"
    assert len({e["tag"] for e in calib_entries}) == EXPECTED_CALIB_TAGS
    assert len(holdout_entries) == EXPECTED_HOLDOUT, f"holdout {len(holdout_entries)}"
    assert len({e["tag"] for e in holdout_entries}) == EXPECTED_HOLDOUT_TAGS

    calib_ids = {e["prompt_id"] for e in calib_entries}
    holdout_ids = {e["prompt_id"] for e in holdout_entries}
    assert not (calib_ids & holdout_ids), "calib/holdout prompt_id overlap"

    old_pids = load_old_prompt_ids()
    if old_pids:
        assert len(old_pids) == EXPECTED_OLD_PIDS, f"old pids {len(old_pids)}"
    old_cross = calib_ids & old_pids
    assert not old_cross, f"calib crosses old split: {sorted(old_cross)}"
    holdout_cross = holdout_ids & old_pids
    assert not holdout_cross, f"holdout crosses old split: {sorted(holdout_cross)}"

    manifest = {
        "schema_version": 1.0,
        "frozen_at": FROZEN_AT,
        "dataset": DATASET,
        "revision": REVISION,
        "license": LICENSE,
        "source_file": SOURCE_FILE,
        "source_sha256": SOURCE_SHA256,
        "selection": {
            "language": "zh",
            "tag_regex": TAG_REGEX,
            "split_unit": "prompt_id",
            "algorithm": ALGORITHM,
            "calibration_buckets": CALIB_BUCKETS,
            "holdout_buckets": HOLDOUT_BUCKETS,
        },
        "zero_cross_proof": {
            "old_manifest": OLD_MANIFEST_PATH.name,
            "old_prompt_id_count": EXPECTED_OLD_PIDS if old_pids else None,
            "calib_cross_old": len(old_cross),
            "holdout_cross_old": len(holdout_cross),
            "calib_holdout_cross": len(calib_ids & holdout_ids),
        },
        "calibration": calib_entries,
        "holdout": holdout_entries,
    }

    OUT_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {OUT_PATH}")
    print(f"  calib={len(calib_entries)}/{EXPECTED_CALIB_TAGS} tags, "
          f"holdout={len(holdout_entries)}/{EXPECTED_HOLDOUT_TAGS} tags")


if __name__ == "__main__":
    main()
