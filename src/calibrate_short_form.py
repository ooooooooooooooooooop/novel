#!/usr/bin/env python3
"""calibrate_short_form — 人类读者校准（隐藏来源连续阅读）CLI 入口.

Q1 Phase 6（docs/00_project/45 §7）：读者只回答 6 问，不展示系统自评/来源/硬标准；
硬标准由零 LLM 门禁链自动判定。产物 output/calibrate/<packet_id>/calibration_report.json。

用法:
    python src/calibrate_short_form.py --output-dir <novel>/output/calibrate \
        --chapters-dir <novel>/chapters --generated-dir <backup> \
        --packet wanwu_pilot_01 --original 22-23 --generated 24-25 --build
    # 首跑：组装材料包 + 硬标准判定 → [WAITING] 读者填 calibration_response.txt
    # 重跑：聚合 → calibration_report.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.object_state.calibratereport import CalibrationReport
from src.workflow_action.calibrate import (
    CalibrateUnit,
    aggregate,
    assemble_packet,
    load_trusted_context,
    run_hard_standards,
    verdicts,
)


def _read_response_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _auto_generated_dir(output_dir: Path) -> Path:
    """未指定 --generated-dir 时，取 output/recovery/chapters_backup_<seq> 中最新一个."""
    recovery_dir = output_dir.parent / "recovery"
    backups = sorted(
        recovery_dir.glob("chapters_backup_*"),
        key=lambda p: (int(p.name.rsplit("_", 1)[-1]) if p.name.rsplit("_", 1)[-1].isdigit() else 0),
    )
    if backups:
        return backups[-1]
    return output_dir.parent.parent / "chapters"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="人类读者校准（隐藏来源连续阅读）：组装材料包 + 问卷 + 聚合报告"
    )
    parser.add_argument("--output-dir", default="output", help="校准输出目录（novels/<名>/output/calibrate）")
    parser.add_argument("--chapters-dir", default="chapters", help="原始可信正文章节目录")
    parser.add_argument(
        "--generated-dir", default="",
        help="AI 生成正文章节目录（默认取 output/recovery/chapters_backup_* 最新）",
    )
    parser.add_argument("--packet", required=True, help="材料包标识（如 wanwu_pilot_01）")
    parser.add_argument("--original", default="", help="原始章号范围（如 22-23）")
    parser.add_argument("--generated", default="", help="生成章号范围（如 24-25）")
    parser.add_argument("--build", action="store_true", help="强制重新组装材料包并跑硬标准判定")
    parser.add_argument("--reader-id", default="reader_1", help="读者标识（默认 reader_1）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = output_dir / args.packet
    packet_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir = Path(args.chapters_dir)
    generated_dir = Path(args.generated_dir) if args.generated_dir else _auto_generated_dir(output_dir)

    reading_path = packet_dir / "reading.txt"
    prompt_path = packet_dir / "calibrate_prompt.txt"
    response_path = packet_dir / "calibration_response.txt"
    config_path = packet_dir / "packet_config.json"
    hard_standards_path = packet_dir / "hard_standards.json"
    report_path = packet_dir / "calibration_report.json"

    # Phase 1: 组装材料包（隐藏来源）+ 硬标准自动判定（操作者可见，读者不可见）
    if args.build or not config_path.exists():
        if not args.original or not args.generated:
            print("Error: --build 需要 --original 与 --generated 章号范围")
            return 1
        chapters, reading_path = assemble_packet(
            output_dir,
            args.packet,
            original_spec=args.original,
            generated_spec=args.generated,
            chapters_dir=chapters_dir,
            generated_dir=generated_dir,
        )
        print(f"Assembled packet: {packet_dir}")
        print(f"  reading: {reading_path}")
        for c in chapters:
            print(f"  {c['chapter_ref']}  source={c['source']}")
        facts, characters, contract, time_book = load_trusted_context(output_dir)
        hard = run_hard_standards(
            chapters,
            facts=facts,
            characters=characters,
            time_book=time_book,
            reader_contract=contract,
        )
        hard_standards_path.write_text(
            json.dumps(
                [h.model_dump(mode="json") for h in hard],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        for h in hard:
            marks = " ".join(
                f"{i.issue_type}({i.severity})" for i in h.blocking_issues
            ) or "clean"
            print(f"  hard {h.chapter_ref}: route={h.route}  {marks}")
        print(f"  hard_standards: {hard_standards_path}")

    # Phase 2: 问卷 [WAITING]
    if not response_path.exists():
        hard = json.loads(hard_standards_path.read_text(encoding="utf-8"))
        chapter_refs = [h["chapter_ref"] for h in hard]
        unit = CalibrateUnit()
        prompt = unit.build_prompt(
            chapter_refs=chapter_refs,
            reading_path=reading_path,
            reader_id=args.reader_id,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\n[STEP: CALIBRATE] Prompt saved: {prompt_path}")
        print(f"[WAITING] 阅读 {reading_path} 后按问卷填写响应: {response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    # Phase 3: 聚合 → calibration_report.json
    response = _read_response_text(response_path)
    source_map = json.loads(
        (packet_dir / "source_map.json").read_text(encoding="utf-8")
    )
    hard = [
        h
        for h in json.loads(hard_standards_path.read_text(encoding="utf-8"))
    ]
    # 反序列化 hard_standards（直接透传 report 用，故转对象）
    from src.object_state.calibratereport import CalibrationHardStandard

    hard_objects = [CalibrationHardStandard(**h) for h in hard]
    expected_refs = [h.chapter_ref for h in hard_objects]
    unit = CalibrateUnit()
    reader = unit.parse_response(response, expected_chapter_refs=expected_refs)
    agg = aggregate(source_map, hard_objects, reader)
    ver = verdicts(source_map, hard_objects, reader)
    report = CalibrationReport(
        schema_version=1,
        packet_id=args.packet,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        source_map=source_map,
        hard_standards=hard_objects,
        reader=reader,
        aggregate=agg,
        verdicts=ver,
    )
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {report_path}")
    print(f"packet: {args.packet} | reader: {reader.reader_id}")
    print(f"  continue_ratio: {agg.continue_ratio}  same_character_ratio: {agg.same_character_ratio}")
    print(f"  genre_change: {agg.genre_change}")
    print(f"  走神锚点: {len(agg.wander_anchors)} | 不可信事实: {len(agg.disbelieved_facts)}")
    print(f"  verdicts (pilot): original_clean={ver.original_clean} generated_clean={ver.generated_clean} "
          f"reader_continue={ver.reader_continue} reader_genre_stable={ver.reader_genre_stable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
