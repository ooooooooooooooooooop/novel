#!/usr/bin/env python3
"""style_short_form — 写作风格提炼 CLI 入口.

从已有小说文本提炼 StyleProfile：
  1. 量化分析（纯代码，无需 LLM）
  2. LLM 质性提炼（response-file 循环）
  3. 合并 → style_profile.json
  4. --lint 时产出 style_lint_report.json

用法:
    python src/style_short_form.py <input.txt> --output-dir <dir> [--lint]
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.chunking import get_total_stats, split_by_chapters
from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.boundary_control.style_metrics import analyze_style_metrics
from src.domain_layer.style_rules import (
    build_style_knowledge_context,
    build_worldview_axis_guidance,
)
from src.workflow_action.outline import OutlineUnit
from src.workflow_action.style import (
    STYLE_DEDUP_THRESHOLD,
    StyleExtractUnit,
    StyleLintUnit,
    auto_style_id,
    find_most_similar,
    load_style_context,
    load_style_manifest,
    resolve_style_library_path,
    search_style_manifest,
    style_library_dir,
    style_library_profile_path,
    upsert_style_manifest,
)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def _read_response_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _run_reference_mode(args: argparse.Namespace, text: str, output_dir: Path) -> int:
    """--style 引用模式：加载风格库档案，配 --lint 时做禁忌词 style_drift 检查.

    不提炼档案（档案已存在于库中），只消费。返回 0 表示完成。
    """
    from src.object_state.styleprofile import StyleProfile

    library_path = resolve_style_library_path(args.style)
    if not library_path.exists():
        print(f"Error: style library profile not found: {library_path}")
        print("Run `novel style <小说>` to auto-save, or use --style-search to find an id.")
        return 1

    profile = StyleProfile.model_validate_json(library_path.read_text(encoding="utf-8"))
    print(f"Loaded style library profile: {library_path}")
    print(f"Tone: {profile.tone_labels}")
    print(f"Taboo words: {profile.taboo_words}")

    if args.lint:
        lint_unit = StyleLintUnit()
        issues = lint_unit.lint_taboo_words(text, profile.taboo_words)
        lint_report = {
            "source_text_ref": str(Path(args.input_file).resolve()),
            "style_reference": args.style,
            "issue_count": len(issues),
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }
        lint_report_path = output_dir / "style_lint_report.json"
        lint_report_path.write_text(
            json.dumps(lint_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved lint report: {lint_report_path} ({len(issues)} issues)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="从小说文本提炼写作风格档案")
    parser.add_argument("input_file", nargs="?", default="input.txt", help="输入文本路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--lint",
        action="store_true",
        help="对全文做 AI 味 lint，产出 style_lint_report.json",
    )
    parser.add_argument(
        "--tone",
        default="",
        help="调性提示词（可选，注入风格知识分类轴，如 克制）",
    )
    parser.add_argument(
        "--genre",
        default="",
        help="类型提示词（可选，注入 genre 风格知识，如 仙侠）",
    )
    parser.add_argument(
        "--temperament",
        default="",
        help="叙事气质先验（可选，注入气质桶风格知识，如 散文型）",
    )
    parser.add_argument(
        "--name",
        default="",
        help="将提炼出的档案另存到风格库 style_library/<name>.json（可跨小说复用）",
    )
    parser.add_argument(
        "--style",
        default="",
        help="引用风格库中的已有档案 <id 或文件名>，跳过提炼；配 --lint 时对全文做禁忌词 style_drift 检查",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="入库时忽略相似度去重提示，强制新建档案",
    )
    parser.add_argument(
        "--no-library",
        action="store_true",
        help="提炼结果不写入风格库（跳过自动入库）",
    )
    parser.add_argument(
        "--style-search",
        metavar="QUERY",
        default="",
        help="在风格库 manifest 上做关键词检索（tone/genre/pov/句式），列出候选 id 后退出",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --style-search：在风格库 manifest 上检索候选 id（不需输入文本）
    if args.style_search:
        manifest = load_style_manifest()
        results = search_style_manifest(manifest, args.style_search)
        if not results:
            print(f"Style library: no match for query {args.style_search!r}")
            return 1
        print(f"Style library: {len(results)} match(es) for {args.style_search!r}")
        for entry in results:
            sig = "; ".join(entry.get("key_signatures") or [])[:80]
            print(
                f"  {entry.get('id')}  <{entry.get('file')}>  "
                f"[{'/'.join(entry.get('tone_labels') or [])}] "
                f"{entry.get('genre_guess')} — {sig}"
            )
        return 0

    text_path = Path(args.input_file)
    if not text_path.exists():
        print(f"Error: Input file not found: {text_path}")
        return 1
    text = _read_text(text_path)

    # --style 引用模式：不提炼，直接加载库档案 + 可选禁忌词 lint
    if args.style:
        return _run_reference_mode(args, text, output_dir)

    # Step 0: hash check
    hash_path = output_dir / ".input_hash"
    current_hash = file_content_hash(text_path)
    hash_errors = validate_run_hash(
        hash_path=hash_path,
        current_hash=current_hash,
        output_dir=output_dir,
        label="input file",
    )
    if hash_errors:
        for error in hash_errors:
            print(error)
        return 1

    # Step 1: chunk + stats
    chunks = split_by_chapters(text)
    total_stats = get_total_stats(chunks)
    print(f"Loaded text: {len(text)} chars, {len(chunks)} chapters")

    # Step 2: quantitative pass (pure code)
    print("\n" + "=" * 50)
    print("Quantitative Style Analysis")
    print("=" * 50)
    stats = analyze_style_metrics(text)
    lint_unit = StyleLintUnit()
    risks = lint_unit.lint_stats(stats)
    print(f"总字数: {stats.total_chars} | 句子数: {stats.sentence_count}")
    print(f"平均句长: {stats.avg_sentence_len} 字符 | 短句占比: {stats.short_sentence_ratio:.2f} | 长句占比: {stats.long_sentence_ratio:.2f}")
    print(f"对话占比: {stats.dialogue_ratio:.2f}")
    print(f"弱化副词密度: {stats.weak_adverb_density_per_1000}/千字 {dict(stats.weak_adverb_counts)}")
    if stats.metaphor_repeats:
        print(f"重复喻体: {[(m.vehicle, m.count) for m in stats.metaphor_repeats]}")
    else:
        print("重复喻体: 无")
    print(f"解释腔: {stats.explanatory_phrase_count} | 壳句式: {dict(stats.shell_counts)}")
    print(f"对话标签密度: {stats.dialogue_tag_density_per_1000}/千字 | 情绪宣布词: {stats.emotion_announcement_count}")
    print(f"破折号+冒号密度: {stats.dash_colon_density_per_1000}/千字")
    print(f"AI 味风险: {len(risks)}")
    for risk in risks:
        print(f"  [{risk.severity}] {risk.rule_id}: {risk.measure} {risk.value}（阈值{risk.threshold}）")

    # Step 3: LLM qualitative extraction (response-file loop)
    extract_unit = StyleExtractUnit()
    extract_prompt_path = output_dir / "style_extract_prompt.txt"
    extract_response_path = output_dir / "style_extract_response.txt"
    profile_path = output_dir / "style_profile.json"

    if not extract_response_path.exists():
        samples = OutlineUnit().sample_chapters(chunks)
        samples_text = "\n\n".join(
            f"--- 第{sample.chapter_index}章: {sample.chapter_title} ---\n"
            f"{sample.sample_text}"
            for sample in samples
        )
        quantitative_context = _render_quantitative_context(stats, risks)
        style_knowledge_context = build_style_knowledge_context(
            tone=args.tone, genre=args.genre, temperament=args.temperament
        )
        prompt = extract_unit.build_prompt(
            samples_text=samples_text,
            total_stats=total_stats,
            quantitative_context=quantitative_context,
            style_knowledge_context=style_knowledge_context,
            temperament=args.temperament,
            worldview_axis_context=build_worldview_axis_guidance(),
        )
        extract_prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\n[STEP: EXTRACT] Prompt saved: {extract_prompt_path}")
        print(f"[WAITING] Generate response to: {extract_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    # Step 4: parse + merge
    response = _read_response_text(extract_response_path)
    qualitative = extract_unit.parse_response(response)
    profile = extract_unit.merge(
        qualitative,
        stats=stats,
        risks=risks,
        source_text_ref=str(text_path),
    )
    profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {profile_path}")
    print(f"Tone: {profile.tone_labels}")
    print(f"Genre guess: {profile.genre_guess}")
    print(f"POV: {profile.narrative_pov}")
    print(f"Closed-loop objects: {profile.closed_loop_objects}")
    print(f"Taboo words: {profile.taboo_words}")
    print(f"Confidence gaps: {profile.confidence_gaps}")

    # 入库到风格库（可跨小说复用）
    #   --name NAME：按给定名字入库；否则自动生成风格化中性 id（克制-官商-001）
    #   自动入库前与库中档案算相似度，≥ STYLE_DEDUP_THRESHOLD 且未 --force 时提示复用，不新建
    if args.name:
        style_id = args.name
        style_library_profile_path(style_id)  # 校验名字合法（非法抛 ValueError）
    elif args.no_library:
        print("Style library: skipped (--no-library)")
        style_id = None
    else:
        manifest = load_style_manifest()
        top_id, top_score = find_most_similar(profile, manifest)
        if top_id and top_score >= STYLE_DEDUP_THRESHOLD and not args.force:
            print(
                f"Style library: new style is {top_score:.0%} similar to "
                f"'{top_id}' — not auto-saved. Reuse with --style {top_id}, "
                f"or save anyway with --force."
            )
            style_id = None
        else:
            style_id = auto_style_id(profile, manifest)
            if top_id:
                if args.force:
                    note = f"--force overrides similarity with '{top_id}' ({top_score:.0%})"
                else:
                    note = f"nearest '{top_id}' ({top_score:.0%}) is below threshold"
                print(f"Style library: {note}; saving {style_id}")
            else:
                print(f"Style library: first entry, saving {style_id}")

    if style_id:
        manifest = load_style_manifest()
        library_path = style_library_dir() / f"{style_id}.json"
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        upsert_style_manifest(
            profile, style_id=style_id, file_name=f"{style_id}.json"
        )
        print(f"Saved to style library: {library_path}")

    # Step 5: optional lint
    if args.lint:
        issues = lint_unit.lint(text)
        lint_report = {
            "source_text_ref": str(text_path),
            "issue_count": len(issues),
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }
        lint_report_path = output_dir / "style_lint_report.json"
        lint_report_path.write_text(
            json.dumps(lint_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved lint report: {lint_report_path} ({len(issues)} issues)")

    return 0


def _render_quantitative_context(stats, risks) -> str:
    """渲染量化分析文本（供 LLM 提炼 prompt 使用）."""
    lines = [
        f"- 总字数: {stats.total_chars} | 句子数: {stats.sentence_count}",
        f"- 平均句长: {stats.avg_sentence_len} 字符 | 短句占比(≤8字): {stats.short_sentence_ratio:.2f} | 长句占比(≥30字): {stats.long_sentence_ratio:.2f}",
        f"- 对话占比: {stats.dialogue_ratio:.2f}",
        f"- 弱化副词密度: {stats.weak_adverb_density_per_1000}/千字（阈值3）",
    ]
    if stats.metaphor_repeats:
        lines.append(
            f"- 重复喻体: {', '.join(m.vehicle + '×' + str(m.count) for m in stats.metaphor_repeats)}"
        )
    else:
        lines.append("- 重复喻体: 无（同喻体≤2 处）")
    lines.append(f"- 解释腔: {stats.explanatory_phrase_count}（阈值1）")
    lines.append(f"- 壳句式: {dict(stats.shell_counts)}")
    lines.append(f"- 对话标签密度: {stats.dialogue_tag_density_per_1000}/千字 | 情绪宣布词: {stats.emotion_announcement_count}")
    lines.append(f"- 破折号+冒号密度: {stats.dash_colon_density_per_1000}/千字")
    # ---- v2: 叙事维度量化（供 LLM 做质性判断） ----
    lines.append(f"- 景物名词密度: {stats.scenery_density_per_1000}/千字 | 景物句占比: {stats.scenery_sentence_ratio:.2f}")
    lines.append(f"- 感官动词密度: {stats.sensory_density_per_1000}/千字")
    lines.append(f"- 场景转换计数: {stats.scene_transition_count} | 时间标记密度: {stats.time_marker_density_per_1000}/千字")
    lines.append(f"- 心理动词密度: {stats.psych_verb_density_per_1000}/千字 | 心理句占比: {stats.psych_sentence_ratio:.2f} | 内独白句占比: {stats.inner_monologue_sentence_ratio:.2f}")
    lines.append(f"- 动作动词密度: {stats.action_verb_density_per_1000}/千字 | 动作句占比: {stats.action_sentence_ratio:.2f}")
    lines.append(f"- 叙述句占比: {stats.narration_sentence_ratio:.2f}")
    # ---- v3: 世界观代理指标（供 LLM 做质性判断；诚实标注是代理信号） ----
    lines.append(f"- 修饰词负载: {stats.modifier_load_density}/千字（白描负代理）")
    lines.append(f"- 旁观者反应密度: {stats.bystander_reaction_density}/千字 | 旁观句占比: {stats.foil_sentence_ratio:.2f}（衬托/侧面代理）")
    lines.append(f"- 显式省略标记: {stats.omission_marker_count} 处（显式留白代理，隐式不可量化）")
    lines.append(f"- 显式决策依据信号: {stats.decision_grounding_marker_density}/千字（只捕捉显式信号）")
    lines.append(f"- 关键段/过渡段字数比: {stats.key_segment_len_ratio:.2f}（密疏代理）")
    if risks:
        lines.append("- AI 味风险:")
        for risk in risks:
            lines.append(
                f"  - [{risk.rule_id}] {risk.measure}: {risk.value}（阈值{risk.threshold}）"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
