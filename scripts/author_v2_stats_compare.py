"""V1 vs V2 vs 真实 统计分布比较（任务 #27）。

比较真实<AUTHOR_ID> / V1生成 / V2生成 的 Polish 与作者信号分布，不止看均值：
- 均值 / 方差 / 分位数(P10,P50,P90) / 长尾(最大)
- 章节内波动（CV）与章节间波动

指标（每章）：
- 句长均值/CV、段长均值/CV、对白比、标点多样性
- 俗语密度（老子/你爹/臭小子/王八蛋/花花肠子/娘们）
- 直给密度（心中暗暗/心中大喜/心中懊悔/不由得/暗暗）
- 点破密度（言外之意/说白了/要知道/这便）
- 收尾精致度（末段长度 + 是否含意象性收尾词）

用法：python scripts/author_v2_stats_compare.py
"""
import json
import os
import re
import sys
from collections import defaultdict

BASE = os.path.join("novels", "_corpus", "authors", "<AUTHOR_ID>")
VAL = os.path.join(BASE, "validation")
OUT = os.path.join(BASE, "validation", "v2_stats_compare.json")

COLLOQ = ["老子", "你爹", "臭小子", "王八蛋", "花花肠子", "娘们", "傻大姐"]
TELL = ["心中暗暗", "心中大喜", "心中懊悔", "不由得", "暗暗想道", "心中一惊", "心中冷笑"]
POINT = ["言外之意", "说白了", "要知道", "这便", "分明", "其实他"]
RUSH_END = ["刻不容缓", "事不宜迟", "迫在眉睫", "火烧眉毛"]


def s_stats(text):
    parts = re.split(r"[。！？…；]", text)
    lens = [len(p) for p in parts if len(p) > 1]
    if not lens:
        return 0, 0
    m = sum(lens) / len(lens)
    v = (sum((x - m) ** 2 for x in lens) / len(lens)) ** 0.5
    return round(m, 1), round(v / m, 3)


def p_stats(text):
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    lens = [len(p) for p in paras]
    if not lens:
        return 0, 0, 0
    m = sum(lens) / len(lens)
    v = (sum((x - m) ** 2 for x in lens) / len(lens)) ** 0.5
    return round(m, 1), round(v / m, 3), len(lens)


def dia_ratio(text):
    in_q = False
    cnt = 0
    for ch in text:
        if ch in "“”\"「」":
            in_q = not in_q
        elif in_q:
            cnt += 1
    return round(cnt / max(1, len(text)), 3)


def count_any(text, markers):
    return sum(text.count(m) for m in markers)


def chapter_metrics(text):
    sm, scv = s_stats(text)
    pm, pcv, pn = p_stats(text)
    last_paras = [p.strip() for p in text.split("\n") if p.strip()]
    last_len = len(last_paras[-1]) if last_paras else 0
    return {
        "s_len_mean": sm, "s_len_cv": scv,
        "para_len_mean": pm, "para_len_cv": pcv, "n_paras": pn,
        "dialogue": dia_ratio(text),
        "colloquial": count_any(text, COLLOQ),
        "tell": count_any(text, TELL),
        "point": count_any(text, POINT),
        "rush_end": count_any(text, RUSH_END),
        "last_para_len": last_len,
    }


def aggregate(chaps_metrics, label):
    if not chaps_metrics:
        return None
    def stats(key):
        vals = [c[key] for c in chaps_metrics]
        vals.sort()
        n = len(vals)
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / n
        return {
            "mean": round(mean, 3),
            "sd": round(var ** 0.5, 3),
            "p10": vals[max(0, int(n * 0.1))],
            "p50": vals[int(n * 0.5)],
            "p90": vals[min(n - 1, int(n * 0.9))],
            "max": vals[-1],
        }
    return {k: stats(k) for k in chaps_metrics[0].keys()}


def load_group(name, files):
    ms = []
    for f in files:
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8") as fh:
            ms.append(chapter_metrics(fh.read()))
    return ms


def main() -> int:
    # 真实<AUTHOR_ID>：10部训练作品（每部10章）+ <HIDDEN_WORK>前6章
    real_files = []
    for d in sorted(os.listdir(BASE)):
        p = os.path.join(BASE, d)
        if not os.path.isdir(p) or d in ("validation", "noise_audit"):
            continue
        for f in sorted(os.listdir(p)):
            if f.endswith(".txt"):
                real_files.append(os.path.join(p, f))
    # 去掉<HIDDEN_WORK>隐藏 chapter_010（真实第七章，不参与真实分布——它是对照样本）
    # 但真实分布应含其他真实章；这里全含（含隐藏前6章，是已知前文）

    real_ms = load_group("real", real_files)
    real = aggregate(real_ms, "real")

    # V1 生成（上一轮）
    v1 = {
        "v1_A": load_group("v1_A", [os.path.join(VAL, "arm_A_full.md")]),
        "v1_B": load_group("v1_B", [os.path.join(VAL, "arm_B_work_only.md")]),
        "v1_C": load_group("v1_C", [os.path.join(VAL, "arm_C_author_only.md")]),
    }

    # V2 生成（本轮）
    v2 = {
        "v2_A": load_group("v2_A", [os.path.join(VAL, "v2_arm_A.md")]),
        "v2_B": load_group("v2_B", [os.path.join(VAL, "v2_arm_B.md")]),
        "v2_C": load_group("v2_C", [os.path.join(VAL, "v2_arm_C.md")]),
    }

    out = {"real": real, "v1": {k: aggregate(v, k) for k, v in v1.items()},
           "v2": {k: aggregate(v, k) for k, v in v2.items()}}

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[OUT] {OUT}")

    # 摘要打印：真实 vs V1均值 vs V2均值 的关键维度
    keys = ["s_len_cv", "para_len_cv", "dialogue", "colloquial", "tell", "point"]
    print(f"\n{'dim':<10} {'real.mean':>9} {'real.sd':>8} {'v1mean':>8} {'v2mean':>8} {'v1.sd':>8} {'v2.sd':>8}")
    for k in keys:
        r = out["real"][k]
        v1m = [out["v1"][x][k]["mean"] for x in out["v1"] if out["v1"][x]]
        v2m = [out["v2"][x][k]["mean"] for x in out["v2"] if out["v2"][x]]
        v1s = [out["v1"][x][k]["sd"] for x in out["v1"] if out["v1"][x]]
        v2s = [out["v2"][x][k]["sd"] for x in out["v2"] if out["v2"][x]]
        v1mm = sum(v1m) / len(v1m) if v1m else 0
        v2mm = sum(v2m) / len(v2m) if v2m else 0
        v1ss = sum(v1s) / len(v1s) if v1s else 0
        v2ss = sum(v2s) / len(v2s) if v2s else 0
        print(f"{k:<10} {r['mean']:>9} {r['sd']:>8} {v1mm:>8} {v2mm:>8} {v1ss:>8} {v2ss:>8}")
    print("\n（注：v1/v2 均值跨 A/B/C 取平均；sd 为章节间标准差的平均，反映章节间波动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
