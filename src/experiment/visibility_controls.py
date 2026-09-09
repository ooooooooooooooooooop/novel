"""Small synthetic development controls; exports prompts and scores saved replies.

No provider calls. Expected labels are author annotations, not independent truth.
Prompts never include those labels. Same-author fixture replays only test scoring.
"""
import argparse
from pathlib import Path

from src.experiment.state_selection_probe import json_text, sha, write_frozen
from src.experiment.visibility_preflight import build_visibility_preflight, check_visibility_response


# Fixed order intentionally interleaves labels; IDs do not disclose expectations.
CONTROLS = (
    ("v01", "账册藏在钟楼。", "目标：写出账册藏在钟楼这一事实。", "conflict", "直接披露"),
    ("v02", "账册藏在钟楼。", "只写守卫检修钟楼的大门，不提账册及其位置。", "compatible", "同名地点不是披露"),
    ("v03", "线人的来源未暴露。", "写出队长接过纸条的动作。", "inconclusive", "没有具体秘密值"),
    ("v04", "甲想让乙失去资助。", "认知变化：甲明白，只要切断乙背后的财力，自己便能获胜；在正文中展开这一内心判断。", "conflict", "改写后的动机披露"),
    ("v05", "账册藏在钟楼。", "只写守卫猜测账册也许在钟楼；叙述不确认这个猜测，不描写实际藏处。", "compatible", "猜测不等于事实确认"),
    ("v06", "甲就是送信人。", "让他坦白自己的身份。", "inconclusive", "代词和身份指向不足"),
    ("v07", "钥匙藏在红箱。", "向读者确认钥匙就在两个箱子之一；接着确认蓝箱是空的。场景只有红箱和蓝箱，展开以上信息。", "conflict", "组合信息排除后披露"),
    ("v08", "账册藏在钟楼。", "只写守卫坚信账册已经烧毁的对白；不评价其真假，不透露账册的真实状态。", "compatible", "人物信念与世界事实分离"),
    ("v09", "旧约从未记入任何档案。", "写出甲翻看一份档案，其中没有旧约。", "inconclusive", "局部缺席不证明绝对断言"),
)


SCOPE_CONTROLS = (
    ('s01', '消息来源尚未向读者披露。', '只描写队长接过纸条后关门的动作，不解释消息来源。',
     'compatible', '来源具体性缺口不等于本次动作会披露来源'),
    ('s02', '消息来源尚未向读者披露。', '让队长向读者解释消息来自谁；这里没有提供来源身份。',
     'inconclusive', '要求披露但秘密值不足，不能编造相容性'),
    ('s03', '旧安排从未记入任何正式档案。', '只交代旧安排要求信使绕路，不写任何档案或记录情况。',
     'compatible', '安排内容不是未入档这一完整命题'),
    ('s04', '旧安排从未记入任何正式档案。', '由可信叙述者向读者确认：所有正式档案中都没有旧安排的记录。',
     'conflict', '完整全称命题被明确披露，无须先证明为真'),
)

# Preserve preregistered labels; do not retroactively improve measured accuracy.
SCOPE_LABEL_NOTES = {
    's02': 'Post-run adjudication proposes conflict: disclosure object is explicit despite missing identity value. '
           'Original inconclusive label is retained for historical scoring; not a trusted future gold label.'
}


def materials(suite: str = 'legacy'):
    """Minimal candidates isolate the reviewer contract, not Continue parsing."""
    rows = []
    controls = {'legacy': CONTROLS, 'scope': SCOPE_CONTROLS}[suite]
    for case_id, secret, writer, expected, rationale in controls:
        candidate = {"new_state": {"hidden_information": [secret]}}
        packet = build_visibility_preflight(candidate, writer)
        rows.append(dict(case_id=case_id, writer=writer, packet=packet,
                         expected=expected, rationale=rationale))
    return rows


def export(directory: Path, suite: str = 'legacy'):
    rows = materials(suite)
    (directory / 'prompts').mkdir(parents=True, exist_ok=True)
    files = {f"prompts/{r['case_id']}.txt": r['packet']['prompt'] for r in rows}
    files['manifest.json'] = json_text({
        "purpose": "synthetic_development_controls_not_holdout",
        "model_calls": 0,
        "suite": suite,
        "disputed_legacy_labels": ['v03', 'v09'] if suite == 'legacy' else [],
        "post_run_label_notes": SCOPE_LABEL_NOTES if suite == 'scope' else {},
        "prompts": {name: sha(value) for name, value in files.items()},
        "cases": [{k: r[k] for k in ('case_id', 'expected', 'rationale')} for r in rows],
        "label_source": "current_assistant_design_annotations",
    })
    write_frozen(directory, files)


def score(responses: dict[str, str], suite: str = 'legacy') -> dict:
    rows = materials(suite)
    if set(responses) - {r['case_id'] for r in rows}:
        raise ValueError('unknown visibility control response ID')
    outcomes = []
    matrix = {label: {pred: 0 for pred in ('compatible', 'conflict', 'inconclusive')}
              for label in ('compatible', 'conflict', 'inconclusive')}
    for row in rows:
        result = dict(case_id=row['case_id'], expected=row['expected'])
        if row['case_id'] not in responses:
            result['status'] = 'missing'
        else:
            response = responses[row['case_id']]
            result['response_sha256'] = sha(response)
            try:
                checked = check_visibility_response(response, row['packet'], row['writer'])
            except ValueError as exc:
                result.update(status='invalid', error=str(exc))
            else:
                verdict = checked['assessments'][0]['verdict']
                result.update(status='valid', predicted=verdict)
                matrix[row['expected']][verdict] += 1
        outcomes.append(result)
    valid = sum(r['status'] == 'valid' for r in outcomes)
    correct = sum(matrix[label][label] for label in matrix)
    return dict(suite=suite, planned=len(rows), valid=valid,
                post_run_label_notes=SCOPE_LABEL_NOTES if suite == 'scope' else {},
                disputed_legacy_labels=['v03', 'v09'] if suite == 'legacy' else [],
                missing=sum(r['status'] == 'missing' for r in outcomes),
                invalid=sum(r['status'] == 'invalid' for r in outcomes),
                correct=correct, accuracy_valid=correct / valid if valid else None,
                false_release=matrix['conflict']['compatible'] + matrix['inconclusive']['compatible'],
                false_reject=matrix['compatible']['conflict'] + matrix['compatible']['inconclusive'],
                confusion_matrix=matrix, outcomes=outcomes,
                independent_reviewer_accuracy_established=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=['legacy', 'scope'], default='legacy')
    parser.add_argument('--responses', type=Path,
                        help='Optional directory of v01.json ... v09.json; never invokes a model.')
    args = parser.parse_args()
    # Also verifies frozen prompts before scoring with the current implementation.
    export(args.output, args.suite)
    if args.responses is not None:
        if not args.responses.is_dir():
            parser.error('responses directory does not exist')
        replies = {p.stem: p.read_text(encoding='utf-8') for p in args.responses.glob('*.json')}
        write_frozen(args.output, {'score.json': json_text(score(replies, args.suite))})
    print('VISIBILITY_CONTROLS_READY; model_calls=0; state_commits=0')


if __name__ == '__main__':
    main()
