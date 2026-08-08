"""Hindsight Reconciliation — 几章后补写 ChoiceRecord 的真后果（作者性 §11-12 闭环）.

Gate 1 的关键断裂点：`record_consequence` / `record_hindsight` 过去只有 API、无
生产闭环调用——ChoiceRecord 永远停在决策时刻的自述理由，Consequence 从未从
「后来的真实故事结果」补写。本模块补上这一环：

```
ChoiceRecord(decision, chapter N)
        ↓ 几章后（证据 = 已提交的 chapter N+1... 真实正文）
Hindsight Reconcile（LLM，读证据）
        ↓
record_consequence(实际后果) + record_hindsight(仍支持/部分后悔/推翻/复杂/未明)
        ↓
下次 Consolidation：hindsight ∈ {overturned, partial_regret} → 反例证据
        ↓
AuthorKernel 更新 → 未来 Selection
```

**禁止伪后果**：consequence 必须依附已提交章节的 evidence（正文/后续 PlotUnit），
不允许决策时刻的即时自我解释。prompt 只给「当初选了什么 + 之后真的发生了什么」，
judge 据此判定，且 judge 不知道当初理由的预期方向。

隐私：含作品语境，prompt/响应存 `novels/<名>/output/hindsight/`，本地 gitignored。
"""

import json
from pathlib import Path
from typing import Optional

from src.object_state.choicerecord import (
    ChoiceLedgerEntry,
    ChoiceRecord,
    HindsightStatus,
)
from src.workflow_action.choiceledger import (
    load_choice_ledger,
    record_consequence,
    record_hindsight,
)

HINDSIGHT_PROMPT_FILE = "hindsight_prompt.txt"
HINDSIGHT_RESPONSE_FILE = "hindsight_response.txt"
HINDSIGHT_DIR = "hindsight"
# 至少滞后多少章才有「真实后果」证据（防即时自我解释）
DEFAULT_LAG = 2


# ---------------------------------------------------------------------------
# 开放性选择
# ---------------------------------------------------------------------------
def open_choices(
    ledger: ChoiceLedgerEntry,
    *,
    current_chapter: Optional[int] = None,
    lag: int = DEFAULT_LAG,
) -> list[ChoiceRecord]:
    """尚无 consequence 且证据已足够（≥lag 章之后）的选择记录."""
    open_records: list[ChoiceRecord] = []
    for choice in ledger.choices:
        if choice.consequence is not None:
            continue
        if choice.chapter_number is None:
            # 无章号（旧记录）：不自动回填，避免证据边界不清
            continue
        if current_chapter is None or choice.chapter_number <= current_chapter - lag:
            open_records.append(choice)
    return open_records


def _selected_candidate(choice: ChoiceRecord) -> Optional[dict]:
    for c in choice.candidates:
        if c.candidate_id == choice.selected_candidate:
            return c.plotunit
    return None


def _render_choice(choice: ChoiceRecord) -> str:
    """渲染一条选择记录（judge 看：当初做了什么选择、放弃什么换什么）."""
    sel = _selected_candidate(choice)
    sel_goal = sel.get("goal", "") if sel else ""
    sel_conflict = sel.get("conflict", "") if sel else ""
    rejected = "; ".join(f"{r.candidate_id}: {r.reason}" for r in choice.rejected)
    conflicts = "/".join(choice.value_conflicts) or "—"
    return (
        f"- decision_id={choice.decision_id}（第{choice.chapter_number}章）\n"
        f"  选中候选 {choice.selected_candidate}：目标『{sel_goal}』冲突『{sel_conflict}』\n"
        f"  触及价值冲突：{conflicts}\n"
        f"  被拒候选：{rejected or '（无）'}\n"
        f"  tradeoff（当初放弃什么换什么）：{choice.tradeoff}"
    )


def _render_evidence(chapters: list[tuple[int, str]]) -> str:
    lines = []
    for num, text in chapters:
        head = text.strip()
        if len(head) > 1500:
            head = head[:1500] + "……（截断）"
        lines.append(f"—— 第{num}章（真实已提交正文）——\n{head}")
    return "\n\n".join(lines)


def build_hindsight_prompt(
    choices: list[ChoiceRecord],
    evidence_chapters: list[tuple[int, str]],
) -> str:
    """构造回看 prompt：只给「当初选了什么 + 之后真的发生了什么」.

    不给预期的 consequences 方向，judge 必须从证据里读实际后果。
    """
    choice_block = "\n\n".join(_render_choice(c) for c in choices)
    evidence_block = _render_evidence(evidence_chapters)
    return f"""你正在为一个长期连载小说补写「创作选择的事后回看」。

下面是几章前做出的创作选择（候选方案、选中者、被拒者、tradeoff），
以及**选择之后真实提交的章节正文**。请只依据这些真实章节证据，判断每一个选择
**后来实际造成了什么**。

规则：
- consequence 必须写「实际发生了什么」（引用具体章节事件/关系变化/伏笔兑现或落空/
  人物为此付出的代价），禁止写「这章写得不错」之类的泛化评价。
- 如果证据里还看不出后果，hindsight 填 "unclear"，consequence 写清现状即可。
- 不要因为你喜欢当时的选择就填 still_supported——凭证据。

【待回看的选择】
{choice_block}

【之后的真实章节（证据）】
{evidence_block}

【输出格式】
严格输出 JSON 数组（顺序与【待回看的选择】一致）：
[
  {{
    "decision_id": "dec_xxx",
    "consequence": "后来实际发生了什么（引用证据）",
    "hindsight": "still_supported|partial_regret|overturned|complex|unclear",
    "note": "一句话回看说明"
  }}
]
"""


def parse_hindsight_response(response: str) -> list[dict]:
    """解析回看响应；字段校验严格（decision_id 必须命中待回看集合）. """
    data = json.loads(response)
    if not isinstance(data, list):
        raise ValueError("hindsight response must be a JSON array")
    if not data:
        raise ValueError("hindsight response must be non-empty")
    allowed = {"decision_id", "consequence", "hindsight", "note"}
    parsed: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("hindsight entry must be an object")
        extra = sorted(set(entry) - allowed)
        if extra:
            raise ValueError(f"hindsight entry has unexpected field(s): {', '.join(extra)}")
        for field in ("decision_id", "consequence"):
            if not isinstance(entry.get(field), str) or not entry.get(field).strip():
                raise ValueError(f"hindsight entry missing non-empty {field}")
        status = entry.get("hindsight")
        if status not in HindsightStatus.__args__:
            raise ValueError(
                f"hindsight must be one of {HindsightStatus.__args__}, got {status!r}"
            )
        parsed.append(entry)
    return parsed


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def reconcile_hindsight(
    output_dir: Path,
    chapters_dir: Path,
    *,
    lag: int = DEFAULT_LAG,
    current_chapter: Optional[int] = None,
    response_path: Optional[Path] = None,
) -> dict:
    """跑一轮 Hindsight Reconciliation（一次处理所有开放性选择）.

    Returns: {"status": "noop"|"prompt"|"done"|"empty",
              "updated": int, "prompt_path": Path|None, ...}
      - noop：无开放性选择（无证据或无滞后）
      - prompt：已写 prompt，等待 operator 填 hindsight_response.txt
      - done：响应已消费并回填
      - empty：响应文件存在但目标 choice 已全部回填（幂等重跑）
    """
    output_dir = Path(output_dir)
    chapters_dir = Path(chapters_dir)
    hindsight_dir = output_dir / HINDSIGHT_DIR
    hindsight_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = hindsight_dir / HINDSIGHT_PROMPT_FILE
    resp_path = response_path or hindsight_dir / HINDSIGHT_RESPONSE_FILE

    ledger = load_choice_ledger(output_dir)
    if current_chapter is None:
        nums = sorted(
            int(p.stem[len("chapter_"):])
            for p in chapters_dir.glob("chapter_*.txt")
            if p.stem[len("chapter_"):].isdigit()
        )
        current_chapter = nums[-1] if nums else None
    if current_chapter is None:
        return {"status": "noop", "updated": 0}

    open_recs = open_choices(ledger, current_chapter=current_chapter, lag=lag)
    if not open_recs:
        return {"status": "noop", "updated": 0}

    # 证据 = 每条选择之后的所有已提交章节（去重合并，供 judge 全文检索）
    evidence_nums = sorted(
        int(p.stem[len("chapter_"):])
        for p in chapters_dir.glob("chapter_*.txt")
        if p.stem[len("chapter_"):].isdigit()
    )
    evidence_chapters: list[tuple[int, str]] = [
        (num, _read_chapter(chapters_dir / f"chapter_{num}.txt"))
        for num in evidence_nums
    ]

    if resp_path.exists():
        # 幂等：响应已存在 → 回填；若对应 choice 已回填则视为 done
        response = resp_path.read_text(encoding="utf-8-sig")
        entries = parse_hindsight_response(response)
        by_id = {e["decision_id"]: e for e in entries}
        expected_ids = {c.decision_id for c in open_recs}
        missing = expected_ids - set(by_id)
        if missing:
            raise ValueError(
                f"hindsight response missing decision_id(s): {sorted(missing)}"
            )
        unknown = set(by_id) - expected_ids
        if unknown:
            raise ValueError(
                f"hindsight response has unknown decision_id(s): {sorted(unknown)}"
            )
        updated = 0
        for c in open_recs:
            entry = by_id[c.decision_id]
            rec_ok = record_consequence(output_dir, c.decision_id, entry["consequence"])
            hin_ok = record_hindsight(
                output_dir,
                c.decision_id,
                entry["hindsight"],
                note=entry.get("note"),
            )
            if rec_ok and hin_ok:
                updated += 1
        return {"status": "done", "updated": updated}
    else:
        prompt_text = build_hindsight_prompt(open_recs, evidence_chapters)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        return {"status": "prompt", "prompt_path": prompt_path, "n_open": len(open_recs)}


def _read_chapter(path: Path) -> str:
    return path.read_text(encoding="utf-8")
