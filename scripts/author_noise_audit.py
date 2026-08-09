"""<AUTHOR_ID>噪声来源审计 + Polish Distribution 度量（任务 #23 / #27 基础）。

两部分：
A. 噪声扫描：已知常见错字/形近/同音替代清单 + 市井俗语标记，跨作品统计重复度 → provenance 判据之一。
B. Polish 度量：每章句长/段长/对白比/标点多样性的均值与 CV → 精致度不均值（Polish Distribution）的代码代理。

输出：novels/_corpus/authors/<AUTHOR_ID>/noise_audit/ （gitignored）
用法：python scripts/author_noise_audit.py
"""
import json
import os
import re
import sys
from collections import defaultdict

BASE = os.path.join("novels", "_corpus", "authors", "<AUTHOR_ID>")
OUT_DIR = os.path.join(BASE, "noise_audit")
os.makedirs(OUT_DIR, exist_ok=True)

# 已知常见错字/形近/同音替代（含上轮 Judge 发现 + 网文常见错误）
KNOWN_ERRORS = {
    "决对": "绝对", "冲满": "充满", "嬴弱": "羸弱", "孟拱": "孟珙",
    "杨国妃": "杨贵妃", "光面堂皇": "冠冕堂皇", "深遂": "深邃",
    "悲伧": "悲怆", "至歉": "道歉", "千万百计": "千方百计",
    "既使": "即使", "以经": "已经", "那怕": "哪怕", "一但": "一旦",
    "按排": "安排", "不只": "不止", "迷芒": "迷茫", "脑侮": "侮辱",
    "连系": "联系", "辩别": "辨别", "相形见拙": "相形见绌",
    "察颜观色": "察言观色", "大声急呼": "大声疾呼",
    "鬼计": "诡计", "以德抱怨": "以德报怨",
}
# 市井俗语/粗糙口语标记（style，非错字）
COLLOQUIAL_MARKERS = ["娘们", "傻大姐", "花花肠子", "夜壶", "死胖子", "你爹", "老子",
                      "俺", "龟儿子", "王八蛋", "狗日的", "臭小子", "小娘皮"]
# 情绪直给标记（tell 非 show）
TELL_MARKERS = ["心中懊悔", "心中暗暗", "心中大喜", "心中一惊", "心里一阵", "暗暗想道",
                "不由得", "暗自思量", "心中冷笑", "心头一热"]
# 仓促收尾标记（章末一句直白利害陈述特征——句末判断式收尾）
RUSH_END_MARKERS = ["刻不容缓", "事不宜迟", "不能再等", "火烧眉毛", "迫在眉睫"]


def sentence_len_stats(text: str):
    """按 。！？……；切句，返回 (mean, cv, n)"""
    parts = re.split(r"[。！？…；]", text)
    lens = [len(p) for p in parts if len(p) > 1]
    if not lens:
        return 0, 0, 0
    m = sum(lens) / len(lens)
    var = sum((x - m) ** 2 for x in lens) / len(lens)
    return m, (var ** 0.5) / m, len(lens)


def para_len_stats(text: str):
    """按换行分段落（去空），返回 (mean, cv, n)"""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    lens = [len(p) for p in paras]
    if not lens:
        return 0, 0, 0
    m = sum(lens) / len(lens)
    var = sum((x - m) ** 2 for x in lens) / len(lens)
    return m, (var ** 0.5) / m, len(lens)


def dialogue_ratio(text: str):
    """对白占比：引号内字符 / 总字符"""
    in_q = False
    cnt = 0
    for ch in text:
        if ch in "“”\"「」":
            in_q = not in_q
            continue
        if in_q:
            cnt += 1
    return cnt / max(1, len(text))


def punct_diversity(text: str):
    """标点多样性：不同标点种类数"""
    return len(set(ch for ch in text if ch in "。，！？；：、……—～「」“”‘’"))


def main() -> int:
    works = []
    for d in sorted(os.listdir(BASE)):
        p = os.path.join(BASE, d)
        if not os.path.isdir(p) or d in ("validation", "noise_audit"):
            continue
        chaps = []
        for f in sorted(os.listdir(p)):
            if not f.endswith(".txt"):
                continue
            with open(os.path.join(p, f), encoding="utf-8") as fh:
                chaps.append(fh.read())
        works.append({"work": d, "chapters": chaps})

    # ========== A. 噪声扫描 ==========
    print("== A. 已知错字/俗语/直给/仓促 跨作品扫描 ==")
    error_rows = []
    for token, correct in KNOWN_ERRORS.items():
        hits = [(w["work"], sum(c.count(token) for c in w["chapters"])) for w in works]
        n_works = sum(1 for _, c in hits if c > 0)
        total = sum(c for _, c in hits)
        if total > 0:
            error_rows.append({
                "token": token, "correct": correct, "n_works": n_works,
                "total": total, "per_work": dict(hits),
            })
            works_list = [w for w, c in hits if c > 0]
            print(f"  {token}→{correct}: {n_works}/{len(works)}作 {total}次  {[w[:10] for w in works_list]}")
    print(f"  错字类型覆盖作品数分布: {sorted(set(r['n_works'] for r in error_rows))}")

    # ========== 俗语/直给/仓促 ==========
    style_rows = {}
    for cat, markers in [("俗语", COLLOQUIAL_MARKERS), ("直给", TELL_MARKERS), ("仓促", RUSH_END_MARKERS)]:
        rows = []
        for m in markers:
            hits = sum(sum(c.count(m) for c in w["chapters"]) for w in works)
            if hits:
                rows.append({"marker": m, "total": hits})
        style_rows[cat] = rows
        print(f"  {cat}: " + ", ".join(f"{r['marker']}×{r['total']}" for r in rows[:8]) + (" …" if len(rows) > 8 else ""))

    # ========== B. Polish 度量 ==========
    print("\n== B. Polish Distribution 度量（每章） ==")
    polish = []
    for w in works:
        w_row = []
        for i, c in enumerate(w["chapters"]):
            sm, scv, sn = sentence_len_stats(c)
            pm, pcv, pn = para_len_stats(c)
            dr = dialogue_ratio(c)
            pd = punct_diversity(c)
            w_row.append({
                "chapter": i + 1,
                "s_len_mean": round(sm, 1), "s_len_cv": round(scv, 3),
                "para_len_mean": round(pm, 1), "para_len_cv": round(pcv, 3),
                "dialogue_ratio": round(dr, 3), "punct_div": pd,
            })
        polish.append({"work": w["work"], "chapters": w_row})
        # 打印每章 CV 范围
        scvs = [r["s_len_cv"] for r in w_row]
        pcvs = [r["para_len_cv"] for r in w_row]
        print(f"  {w['work'][:14]:<16} 句长CV[{min(scvs):.2f}-{max(scvs):.2f}] 段长CV[{min(pcvs):.2f}-{max(pcvs):.2f}]")

    # ========== 输出 ==========
    with open(os.path.join(OUT_DIR, "noise_scan.json"), "w", encoding="utf-8") as f:
        json.dump({"known_errors": error_rows, "style_markers": style_rows}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "polish_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(polish, f, ensure_ascii=False, indent=1)
    print(f"\n[OUT] {OUT_DIR}/noise_scan.json")
    print(f"[OUT] {OUT_DIR}/polish_metrics.json")
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
