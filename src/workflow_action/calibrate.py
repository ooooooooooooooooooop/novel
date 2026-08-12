"""CalibrateUnit — 人类读者校准（隐藏来源连续阅读）工作流.

Q1 Phase 6（docs/00_project/45 §7）：读者只回答 6 问（不展示系统自评、来源、
硬标准）；硬标准由现有零 LLM 门禁链自动判定，聚合为 calibration_report.json。

职责：
- 材料包组装（assemble_packet）：原始章 + 生成章按章号拼成连续阅读文本，来源隐藏；
- 硬标准自动判定（run_hard_standards）：复用提交点门禁链
  （extract_prose_evidence → reconcile_prose_evidence → ReaderQualityGatePolicy）；
- 问卷（CalibrateUnit.build_prompt / parse_response）：6 问严格 JSON；
- 聚合（aggregate / verdicts）：pilot 口径，不预先伪造科学指标。

零成本契约：无 rebuild 包 / 契约 / TimeBook 时对应轴显式降级（unarmed / 不注入），
不改变已有流程字节。
"""

import json
import re
from pathlib import Path

from src.boundary_control.reader_gate import ReaderQualityGatePolicy
from src.object_state.calibratereport import (
    SOURCE_AI,
    SOURCE_ORIGINAL,
    GENRE_CHANGE_OPTIONS,
    SAME_CHARACTER_OPTIONS,
    TURN_PAGE_OPTIONS,
    CalibrationAggregate,
    CalibrationChapterAnswer,
    CalibrationHardStandard,
    CalibrationIssue,
    CalibrationReaderResponse,
    CalibrationVerdict,
)
from src.workflow_action.prose_evidence import extract_prose_evidence
from src.workflow_action.prose_reconcile import build_trusted_snapshot, reconcile_prose_evidence


# --------------------------------------------------------------------------
# 文本 / 章号工具
# --------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def _parse_range(spec: str) -> list[int]:
    """'22-23,25' → [22, 23, 25]；'24' → [24]. 按数值排序去重."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def _chapter_files_map(directory: Path) -> dict[int, Path]:
    """chapters 目录 → {章号: 路径}（chapter_N.txt，前导零无关）."""
    result: dict[int, Path] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("chapter_*.txt")):
        m = re.match(r"chapter_0*(\d+)\.txt$", path.name)
        if m:
            result[int(m.group(1))] = path
    return result


def _labels_from_characters(characters: list) -> dict[str, list[str]]:
    """从 CharacterModel 列表推导实体注册表 {id: [name, id]}; 空返回 {}."""
    labels: dict[str, list[str]] = {}
    for cm in characters or []:
        cid = getattr(cm, "character_id", None)
        name = getattr(cm, "name", None)
        if cid:
            labels[cid] = [label for label in (name, cid) if label]
    return labels


# --------------------------------------------------------------------------
# 材料包组装（隐藏来源）
# --------------------------------------------------------------------------

def assemble_packet(
    output_dir: Path,
    packet_id: str,
    *,
    original_spec: str,
    generated_spec: str,
    chapters_dir: Path,
    generated_dir: Path,
) -> tuple[list[dict], Path]:
    """把原始章 + 生成章拼成连续阅读材料包，来源隐藏.

    产物（output_dir/<packet_id>/）：
    - packet/chapter_<ref>.txt：逐章正文（读者可见，无来源标注）
    - reading.txt：连续阅读文本（## 章号 头）
    - source_map.json：章号 → original/ai_generated（读者不可见）
    - packet_config.json：组装记录（original/generated 范围，重跑读取）

    Returns: (chapters, reading_path)；chapters = [{chapter_ref, source, text, path}]，
    按章号升序（原始 + 生成混排，接缝即分辨力检测点）。
    """
    packet_dir = output_dir / packet_id
    packet_chapters_dir = packet_dir / "packet"
    packet_chapters_dir.mkdir(parents=True, exist_ok=True)

    orig_map = _chapter_files_map(chapters_dir)
    gen_map = _chapter_files_map(generated_dir)

    entries: list[tuple[int, Path, str]] = []
    for n in _parse_range(original_spec):
        src = orig_map.get(n)
        if src is None:
            raise ValueError(f"original chapter {n} not found in {chapters_dir}")
        entries.append((n, src, SOURCE_ORIGINAL))
    for n in _parse_range(generated_spec):
        src = gen_map.get(n)
        if src is None:
            raise ValueError(f"generated chapter {n} not found in {generated_dir}")
        entries.append((n, src, SOURCE_AI))
    entries.sort(key=lambda e: e[0])

    chapters: list[dict] = []
    for _n, src_path, source in entries:
        text = _read_text(src_path)
        ref = src_path.stem
        dst = packet_chapters_dir / f"{ref}.txt"
        dst.write_text(text, encoding="utf-8")
        chapters.append(
            {"chapter_ref": ref, "source": source, "text": text, "path": dst}
        )

    reading = "\n\n".join(f"## {c['chapter_ref']}\n{c['text']}" for c in chapters)
    reading_path = packet_dir / "reading.txt"
    reading_path.write_text(reading, encoding="utf-8")

    source_map = {c["chapter_ref"]: c["source"] for c in chapters}
    (packet_dir / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config = {
        "schema_version": 1,
        "packet_id": packet_id,
        "original": original_spec,
        "generated": generated_spec,
        "chapter_refs": [c["chapter_ref"] for c in chapters],
    }
    (packet_dir / "packet_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chapters, reading_path


# --------------------------------------------------------------------------
# 硬标准自动判定（复用提交点门禁链，零 LLM）
# --------------------------------------------------------------------------

def run_hard_standards(
    chapters: list[dict],
    *,
    facts=None,
    characters: list | None = None,
    time_book=None,
    reader_contract=None,
) -> list[CalibrationHardStandard]:
    """对材料包每章跑零 LLM 门禁链，返回逐章 CalibrationHardStandard.

    复用生产提交点链：extract_prose_evidence → reconcile_prose_evidence →
    ReaderQualityGatePolicy.evaluate。前章 = 材料包内本章之前的章节（连续阅读语义）。
    缺 trusted/契约/前章时对应轴显式 unarmed / 跳过，不静默放行也不阻断。
    """
    labels = _labels_from_characters(characters)
    trusted = build_trusted_snapshot(
        fact_ledger=facts,
        character_model=(characters[0] if characters else None),
        labels=labels or None,
        time_book=time_book,
    )
    policy = ReaderQualityGatePolicy()
    results: list[CalibrationHardStandard] = []
    for i, chapter in enumerate(chapters):
        text = chapter["text"]
        ref = chapter["chapter_ref"]
        prev = [c["text"] for c in chapters[:i]] or None
        package = extract_prose_evidence(
            text,
            package_id=f"pe_{ref}",
            chapter_ref=ref,
            entities=labels or None,
        )
        issues = reconcile_prose_evidence(
            text,
            package,
            prev_chapters=prev,
            trusted=trusted,
            chapter_ref=ref,
        )
        verdict = policy.evaluate(
            draft_text=text,
            reconcile_issues=issues,
            prev_chapters=prev,
            reader_contract=reader_contract,
            chapter_ref=ref,
        )
        blocking = [
            CalibrationIssue(
                issue_type=issue.issue_type,
                severity=issue.severity,
                location=issue.location,
                description=issue.description,
            )
            for issue in verdict.issues
            if issue.is_blocking()
        ]
        results.append(
            CalibrationHardStandard(
                chapter_ref=ref,
                route=verdict.route,
                axes_armed=dict(verdict.axes_armed),
                blocking_issues=blocking,
            )
        )
    return results


def load_trusted_context(output_dir: Path) -> tuple:
    """从 extend 产物加载 FactLedger/CharacterModel/契约/TimeBook（尽力而为）.

    Args:
        output_dir: calibrate 输出目录（novels/<名>/output/calibrate）。

    Returns: (facts, characters, reader_contract, time_book)；任一缺失返回 None，
    消费端显式降级（零成本契约）。
    """
    extend_dir = output_dir.parent / "extend"
    facts: object = None
    characters: list = []
    contract = None
    time_book = None

    pkg_path = extend_dir / "extend_rebuild_package.json"
    if pkg_path.exists():
        try:
            from src.boundary_control.serialization import SerializationBoundaryUnit
            from src.object_state import CharacterModel, FactLedger

            serializer = SerializationBoundaryUnit()
            package = serializer.load(pkg_path)
            objects = serializer.deserialize_package(package)
            characters = [o for o in objects if isinstance(o, CharacterModel)]
            facts = next((o for o in objects if isinstance(o, FactLedger)), None)
        except Exception:
            facts = None
            characters = []

    from src.workflow_action.reader_contract import load_reader_contract
    contract = load_reader_contract(extend_dir)

    from src.workflow_action.timebook import load_time_book
    time_book = load_time_book(output_dir.parent / "time")

    return facts, characters, contract, time_book


# --------------------------------------------------------------------------
# 问卷（6 问）+ 严格 JSON 解析
# --------------------------------------------------------------------------

class CalibrateUnit:
    """生成读者问卷 prompt / 解析严格 JSON 回答（纯函数，可测）."""

    def build_prompt(
        self,
        chapter_refs: list[str],
        reading_path: Path,
        reader_id: str = "reader_1",
    ) -> str:
        """生成隐藏来源读者问卷 prompt.

        读者只读 packet/reading.txt（不展示系统自评/来源/硬标准）后回答 6 问。
        """
        chapters_block = "\n".join(f"- {ref}" for ref in chapter_refs)
        return f"""你是一位普通小说读者，正在连续阅读一部作品的一个片段。请纯粹以读者身份完成问卷。

【阅读材料】
请通读以下文件（连续若干章，只标章号，不说明来源，也不要猜测来源）：
{reading_path}

本包包含 {len(chapter_refs)} 章，顺序如下：
{chapters_block}

【问卷格式】对每一章回答 6 个问题，严格输出 JSON（只输出 JSON，不要 Markdown 代码块）：
{{
  "reader_id": "{reader_id}",
  "chapters": [
    {{
      "chapter_ref": "<章号>",
      "turn_page": "yes|hesitating|no",
      "same_character": "yes|slight_change|no",
      "wander": "<走神位置；没走神写 无>",
      "disbelieved": ["<读不懂或不相信的事实，可空数组>"],
      "what_happened": "<本章真正发生了什么，一句话>",
      "anticipated": "<最期待接下来发生什么，一句话>"
    }}
  ],
  "overall_genre_change": "no|changed|obvious"
}}

【问题定义】
1. turn_page：是否愿意翻下一页继续读？yes=会，hesitating=犹豫，no=不会
2. same_character：人物还是同一个人吗？yes=是，slight_change=有轻微变化，no=已经不像
3. wander：何处开始走神？（具体到位置/内容；没走神写 无）
4. disbelieved：有没有读不懂或不相信的事实？（列具体条目；没有用空数组）
5. what_happened：本章真正发生了什么？（一句话概括）
6. anticipated：你最期待接下来发生什么？（一句话）

【整体题】overall_genre_change：通读后，核心人物或作品类型有没有改变？
no=没有，changed=有变化，obvious=明显改变

每章都必须回答，chapters 覆盖上述全部章号。诚实作答，不要为了「显得认真」而
编造走神或不可信事实——没有就说没有。
"""

    def parse_response(
        self, response: str, expected_chapter_refs: list[str]
    ) -> CalibrationReaderResponse:
        """解析读者严格 JSON 回答，校验逐章覆盖 + 字段合法."""
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("Calibration response must be a JSON object")
        allowed = {"reader_id", "chapters", "overall_genre_change"}
        required = {"chapters", "overall_genre_change"}
        missing = required - set(data)
        if missing:
            raise ValueError(
                "Calibration response missing required field(s): "
                + ", ".join(sorted(missing))
            )
        extra = sorted(set(data) - allowed)
        if extra:
            raise ValueError(
                "Calibration response has unexpected field(s): " + ", ".join(extra)
            )
        chapters_data = data["chapters"]
        if not isinstance(chapters_data, list) or not chapters_data:
            raise ValueError("Calibration response field chapters must be a non-empty list")
        if data["overall_genre_change"] not in GENRE_CHANGE_OPTIONS:
            raise ValueError(
                "Calibration response field overall_genre_change must be one of "
                + ", ".join(GENRE_CHANGE_OPTIONS)
            )
        answers: list[CalibrationChapterAnswer] = []
        for item in chapters_data:
            if not isinstance(item, dict):
                raise ValueError("each chapters entry must be an object")
            for field in ("turn_page", "same_character"):
                value = item.get(field)
                allowed_choices = (
                    TURN_PAGE_OPTIONS if field == "turn_page" else SAME_CHARACTER_OPTIONS
                )
                if value not in allowed_choices:
                    raise ValueError(
                        f"Calibration response chapter field {field} must be one of "
                        + ", ".join(allowed_choices)
                    )
            answers.append(CalibrationChapterAnswer(**item))
        refs = [a.chapter_ref for a in answers]
        if refs != expected_chapter_refs:
            raise ValueError(
                "Calibration response chapters must cover expected refs in order; "
                f"got {refs}, expected {expected_chapter_refs}"
            )
        return CalibrationReaderResponse(
            schema_version=1,
            reader_id=data.get("reader_id") or "reader_1",
            chapters=answers,
            overall_genre_change=data["overall_genre_change"],
        )


# --------------------------------------------------------------------------
# 聚合 + verdict（pilot 口径）
# --------------------------------------------------------------------------

def aggregate(
    source_map: dict[str, str],
    hard_standards: list[CalibrationHardStandard],
    reader: CalibrationReaderResponse,
) -> CalibrationAggregate:
    """跨章聚合读者回答 + 硬标准."""
    answers = {a.chapter_ref: a for a in reader.chapters}
    n = len(answers)
    continue_count = sum(1 for a in answers.values() if a.turn_page == "yes")
    same_count = sum(1 for a in answers.values() if a.same_character == "yes")
    wander = [
        {"chapter_ref": ref, "anchor": a.wander}
        for ref, a in answers.items()
        if a.wander.strip() and a.wander != "无"
    ]
    disbelieved = [
        {"chapter_ref": ref, "fact": fact}
        for ref, a in answers.items()
        for fact in a.disbelieved
        if fact.strip()
    ]
    what = [{"chapter_ref": ref, "summary": a.what_happened} for ref, a in answers.items()]
    anticipated = [
        {"chapter_ref": ref, "text": a.anticipated} for ref, a in answers.items()
    ]
    return CalibrationAggregate(
        continue_ratio=round(continue_count / n, 4) if n else 0.0,
        same_character_ratio=round(same_count / n, 4) if n else 0.0,
        genre_change=reader.overall_genre_change,
        wander_anchors=wander,
        disbelieved_facts=disbelieved,
        what_happened=what,
        anticipated=anticipated,
    )


def verdicts(
    source_map: dict[str, str],
    hard_standards: list[CalibrationHardStandard],
    reader: CalibrationReaderResponse,
) -> CalibrationVerdict:
    """Q1 硬标准 + 读者口径判定（pilot 口径）.

    - original/generated_clean：对应来源章节硬标准无阻塞问题；
    - reader_continue：愿意继续读的章占比 > 0.5；
    - reader_genre_stable：overall_genre_change == no（没有多数读者认为类型改变）。
    """
    by_source: dict[str, list[CalibrationHardStandard]] = {}
    for h in hard_standards:
        by_source.setdefault(source_map.get(h.chapter_ref, ""), []).append(h)

    def _clean(chapters: list[CalibrationHardStandard]) -> bool:
        return all(not h.blocking_issues for h in chapters)

    total = len(reader.chapters)
    continue_count = sum(1 for a in reader.chapters if a.turn_page == "yes")
    return CalibrationVerdict(
        original_clean=_clean(by_source.get(SOURCE_ORIGINAL, [])),
        generated_clean=_clean(by_source.get(SOURCE_AI, [])),
        reader_continue=total > 0 and continue_count / total > 0.5,
        reader_genre_stable=reader.overall_genre_change == "no",
        is_pilot=True,
    )
