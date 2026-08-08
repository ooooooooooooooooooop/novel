#!/usr/bin/env python3
"""length_probe — 『正文偏短』因果诊断（离线，不进入正式章节）.

背景：连续 4 章初稿稳定停在 ~1250 字符（带宽下限 1645），疑似稳定生成吸引点。
四种可能成因对应不同修复方向，不能直接改『必须写更长』。本脚本对**同一固定
PlotUnit** 物化 4 组 prose prompt，只改变一个因素：

    A — baseline：当前 Prose Prompt
    B — 只强化篇幅要求，其他完全不变
    C — 明确允许非状态 Scene Texture，禁止新增剧情事实
    D — 先拆成更完整的 scene beats / experience progression，再成文

用法：
    python src/experiment/length_probe.py --output-dir <dir> --plotunit <json>
    1. 第一次运行：写 prompt_A/B/C/D.txt 后 [WAITING]。
    2. 操作者/模型生成四份正文 draft（同一 PlotUnit、同一状态），
       保存 draft_A/B/C/D.txt。
    3. 重跑：汇总各版长度 + 质量盲看要点，写 length_probe_report.json。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.object_state.plotunit import PlotUnit
from src.workflow_action import prose as prose_action
from src.workflow_action.prose import CHAPTER_LEN_TOLERANCE


def _variant_a(plotunit, state) -> str:
    return prose_action.build_prompt(plotunit, state, target_chapter_chars=1645)


def _variant_b(plotunit, state) -> str:
    """只强化篇幅要求（其他字节不变），把目标从『允许 ±35%』改为硬性下限."""
    p = _variant_a(plotunit, state)
    marker = "【输出格式】"
    if marker not in p:
        raise ValueError("baseline prompt layout changed")
    head = p.split(marker, 1)[0]
    hard = (
        "\n【篇幅硬约束（本轮实验唯一变量）】\n"
        "本章去空白字符数**必须**达到约 1645 字符以上（当前提示你写得明显偏短，"
        "几乎每次都只写到 ~1250）。请以具体的场景动作、对白、感官细节、空间关系、"
        "人物微动作填充到目标长度；**严禁为凑字而注水**（不得重复已说过的内容、"
        "不得空转解释、不得车轱辘话）。\n\n"
    )
    return head + hard + marker + p.split(marker, 1)[1]


def _variant_c(plotunit, state) -> str:
    """明确允许非状态 Scene Texture，禁止新增剧情事实."""
    p = _variant_a(plotunit, state)
    # 替换第 1 条硬约束：区分『状态事实』（禁止）与『场景纹理』（自由）
    old_rule = (
        "1. 只使用 PlotUnit 中明确出现的参与者、事件、后果与释放信息；"
        "不得引入 PlotUnit 之外的新事实、新角色、新设定。"
    )
    new_rule = (
        "1. 状态约束：禁止引入 PlotUnit 之外的新状态事实——新角色、新能力、新世界规则、"
        "新关键背景、重大历史、剧情事实、新的核心秘密，这些不能自由生成。\n"
        "   场景纹理自由：杯子里的半口水、衣料擦过桌角、窗缝的风、一句话说完后先看了一眼门、"
        "灯照不到桌角、鞋底沾着的泥、手停在信封边缘——这些非状态性的感官/空间/微动作细节，"
        "**可以自由生成**，不需要事先在 PlotUnit 中定义，也不需要进入 FactLedger。"
    )
    if old_rule not in p:
        raise ValueError("baseline constraint layout changed")
    return p.replace(old_rule, new_rule)


def _variant_d(plotunit, state) -> str:
    """先拆成更完整的 scene beats / experience progression，再成文."""
    p = _variant_a(plotunit, state)
    # 把 scene_experience 扩展为显式的节拍序列注入
    se = plotunit.scene_experience
    beats = []
    if se is not None:
        beats.append(f"看见：{se.protagonist_sees}")
        for i, ob in enumerate(se.obstacles or []):
            beats.append(f"阻碍{i+1}：{ob}")
        if se.choice_grounding:
            beats.append(f"选择依据：{se.choice_grounding}")
        if se.outcome:
            beats.append(f"结果：{se.outcome}")
        if se.cognition_shift:
            beats.append(f"认知变化：{se.cognition_shift}")
    beat_section = "\n".join(f"  - {b}" for b in beats)
    return p + (
        "\n\n【场景节拍（本轮实验变量：先拆完整 beats 再成文）】\n"
        "把上面的 PlotUnit 展开为以下按序发生的场景节拍，每个节拍至少用 2-3 个"
        "具体动作/物件/对话把它写实，不要跳拍：\n" + beat_section
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="正文偏短因果诊断")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--plotunit", required=True, help="固定 PlotUnit JSON 文件")
    parser.add_argument("--state", default="", help="NarrativeState JSON（可选）")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    exp_dir = out_dir / "length_probe"
    exp_dir.mkdir(parents=True, exist_ok=True)

    plotunit = PlotUnit.model_validate_json(
        Path(args.plotunit).read_text(encoding="utf-8")
    )
    from src.object_state import NarrativeState
    state = NarrativeState(
        state_id="ns_probe",
        current_time="午后",
        current_location="城南旧碑室",
        current_situation="追踪传承者",
    )
    if args.state:
        state = NarrativeState.model_validate_json(
            Path(args.state).read_text(encoding="utf-8")
        )

    variants = {
        "A_baseline": _variant_a,
        "B_strong_length": _variant_b,
        "C_texture_free": _variant_c,
        "D_beats_first": _variant_d,
    }

    missing = []
    for name, fn in variants.items():
        prompt_path = exp_dir / f"prompt_{name}.txt"
        resp_path = exp_dir / f"draft_{name}.txt"
        if not resp_path.exists():
            if not prompt_path.exists():
                prompt_path.write_text(fn(plotunit, state), encoding="utf-8")
            missing.append(prompt_path)

    if missing:
        print(f"[STEP: LENGTH PROBE] {len(missing)} prompt(s) saved:")
        for p in missing:
            print(f"  {p}")
        print("[WAITING] 同一 PlotUnit、同一状态、同一模型——生成四份正文 draft，"
              "保存到 draft_A/B/C/D.txt，然后重跑。")
        print("[HINT] 只改变一个因素：B=强化篇幅、C=允许场景纹理、D=先拆 beats。"
              "请凭直觉写（不要刻意凑到某长度），以便观察自然长度吸引点。")
        return 0

    # 汇总
    report = {"note": "因果诊断：A=baseline / B=强化篇幅 / C=场景纹理 / D=先拆beats"}
    for name in variants:
        text = (exp_dir / f"draft_{name}.txt").read_text(encoding="utf-8")
        compact = len("".join(text.split()))
        report[name] = {
            "chars": compact,
            "above_lower_bound": compact >= int(1645 * (1 - CHAPTER_LEN_TOLERANCE)),
        }
    report_path = exp_dir / "length_probe_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Length probe report: {report_path}")
    for name in variants:
        r = report[name]
        print(f"  {name}: {r['chars']} chars | above_lower_bound={r['above_lower_bound']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
