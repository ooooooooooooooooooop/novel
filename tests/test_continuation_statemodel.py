"""Continue prompt 的 Chapter Packet 注入测试（V2 Context Firewall）.

验证 V2 架构关键点：
1. 无 packet_context 时，prompt 不含【本章上下文包】，字节与旧版一致（零成本）；
2. 有 packet_context 时，【本章上下文包】段出现；
3. 正文模型拿到的只是 Chapter Packet（SELECT 内容），不是 Full State。
"""
from src.object_state import (
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.object_state.charactermodel import CharacterModel
from src.workflow_action.continuation import ContinueUnit


def _research_case():
    from src.experiment.state_selection_probe import ResearchCase, sha
    text = "门口有人等待答复。仓房的木匠在修门。管家和守门人相互信任。账房藏着尚未公开的账册。"

    def quote(exact):
        start = text.index(exact)
        return dict(source_id="s1", start=start, end=start + len(exact), exact=exact)

    def thread(tid, exact, visible, active):
        return dict(thread=dict(thread_id=tid, thread_type="场景线", label=tid,
                                current_state=exact, needs_protagonist=active,
                                can_background=not active, compression="active" if active else "warm"),
                    current=quote(exact), can_reveal=visible)

    return ResearchCase.model_validate(dict(
        case_id="neutral_case", source_group="synthetic", cutoff_chapter=1,
        sources=[dict(source_id="s1", chapter=1, text=text, sha256=sha(text))],
        scene=quote("门口有人等待答复。"),
        threads=[thread("main", "门口有人等待答复。", True, True),
                 thread("background", "仓房的木匠在修门。", True, False),
                 thread("hidden", "账房藏着尚未公开的账册。", False, False)],
        canon_required=[quote("门口有人等待答复。")],
        necessary_relations=[quote("管家和守门人相互信任。")]))


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1", current_time="夜", current_location="江州",
        active_characters=["p1"], current_situation="旧案初结",
        active_conflicts=["官场博弈"],
    )


def _char() -> CharacterModel:
    return CharacterModel(
        character_id="p1", name="周正", identity="商界", outer_goal="推进",
        inner_need="安稳", fear="被牵连", flaw="念旧", strength="识局",
        stance="合作", current_pressure=[], change_trajectory=[], relations={},
    )


def _prompt(packet_context: str = "") -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(), characters=[_char()],
        facts=FactLedger(entries=[]), foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 都市商战", platform=None, genre=None,
        packet_context=packet_context,
    )


def test_zero_cost_empty():
    """无 packet → 不含【本章上下文包】，字节与旧版一致."""
    p1 = _prompt()
    p2 = _prompt(packet_context="")
    assert "【本章上下文包】" not in p1
    assert p1 == p2
    import json
    from src.object_state.narrativestate import INFORMATION_LAYER_GUIDANCE

    assert INFORMATION_LAYER_GUIDANCE in p1
    assert "不能同时保留为输出状态的 hidden_information" in p1
    example = json.JSONDecoder().raw_decode(p1.split("严格输出 JSON:\n", 1)[1])[0]
    state = NarrativeState.model_validate(example["new_state"])
    assert state.private_information_map == {"仅部分角色知晓的信息": ["知情角色ID"]}


def test_packet_section_injected(monkeypatch, tmp_path):
    """有 packet → 【本章上下文包】段出现并含 SELECT 内容."""
    packet = (
        "本章应自然承载：\n- 恒通机芯谈判（接近兑现）\n"
        "本章事实前提：\n- 顾总在场\n行为约束：\n- 不主动解释未公开动机"
    )
    prompt = _prompt(packet_context=packet)
    assert "【本章上下文包】" in prompt
    assert "恒通机芯谈判" in prompt
    assert "不主动解释未公开动机" in prompt

    # Exercise the real research entry and prose handoff, not just a supplied string.
    import json
    import pytest
    from src.experiment import state_selection_probe as probe

    case = _research_case()
    files = probe.build_bundle(case)
    assert "仓房的木匠在修门。" in files['continue_direct.txt']
    assert "仓房的木匠在修门。" not in files['continue_selected.txt']
    for arm in probe.ARMS:
        assert "管家和守门人相互信任。" in files[f'continue_{arm}.txt']
        assert "账房藏着尚未公开的账册。" not in files[f'continue_{arm}.txt']
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    output = tmp_path / '.workspace_local' / 'case'
    probe.prepare(case, output)
    manifest_bytes = (output / 'manifest.json').read_bytes()
    probe.prepare(case, output)
    assert (output / 'manifest.json').read_bytes() == manifest_bytes

    response = json.dumps(dict(
        plotunit=dict(unit_id='p1', level='scene', goal='等到答复', participants=[],
                      conflict='等待', input_state_ref='neutral_case_start', output_state_ref='next',
                      consequences=['得到答复'], is_effective=True),
        new_state=dict(state_id='next', current_time='稍后', current_location='门口', current_situation='得到答复'),
        new_facts=[], confidence_gaps=[]), ensure_ascii=False)
    for arm in probe.ARMS:
        probe.prepare_prose(output, arm, response)
        prose_prompt = (output / arm / 'prose_prompt.txt').read_text(encoding='utf-8')
        assert ('仓房的木匠在修门。' in prose_prompt) == (arm == 'direct')
        assert '管家和守门人相互信任。' in prose_prompt
        assert '账房藏着尚未公开的账册。' not in prose_prompt
    assert not (output / 'chapters').exists()
    (output / 'continue_selected.txt').write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='hash mismatch'):
        probe.prepare_prose(output, 'selected', response)
    with pytest.raises(ValueError, match='frozen artifact differs'):
        probe.prepare(case, output)

    # Actual research handoff: hidden content may re-enter via the plan's goal.
    hidden_candidate = json.loads(response)
    hidden_candidate['plotunit']['goal'] = '让对手误信账册已毁'
    hidden_candidate['new_state']['hidden_information'] = ['账册并未销毁']
    hidden_text = json.dumps(hidden_candidate, ensure_ascii=False)
    gated = tmp_path / '.workspace_local' / 'visibility'
    probe.prepare(case, gated)
    assert probe.prepare_prose(gated, 'selected', hidden_text) == 'VISIBILITY_REVIEW_REQUIRED'
    assert not (gated / 'selected/prose_prompt.txt').exists()
    assert not (gated / 'selected/handoff.json').exists()
    visibility = json.loads((gated / 'selected/visibility_preflight.json').read_text(encoding='utf-8'))
    review_prompt = (gated / 'selected/visibility_prompt.txt').read_text(encoding='utf-8')
    assert '让对手误信账册已毁' in review_prompt and '账册并未销毁' in review_prompt
    assert '不能只搜索 hidden 原始字符串' in review_prompt
    review = dict(review_id=visibility['review_id'], assessments=[dict(
        item_id='hidden_001', verdict='conflict', reason='受控拒绝夹具，不是模型质量证明',
        writer_quotes=['让对手误信账册已毁'])])
    from src.experiment.visibility_preflight import check_visibility_response
    writer = (gated / 'selected/writer_prompt_candidate.txt').read_text(encoding='utf-8')
    fenced = '```json\n' + json.dumps(review) + '\n```'
    normalized = check_visibility_response(fenced, visibility, writer)
    assert normalized['display_fence_removed'] is True
    assert normalized['compatible'] is False
    for malformed in ('说明\n' + fenced, fenced + '\n补充', fenced[:-3],
                      '```json\n' + json.dumps(dict(review, _note='')) + '\n```'):
        with pytest.raises(ValueError):
            check_visibility_response(malformed, visibility, writer)
    for mutate in (
        lambda d: d.update(review_id='stale'),
        lambda d: d.update(assessments=[]),
        lambda d: d['assessments'].append(d['assessments'][0].copy()),
        lambda d: d['assessments'][0].update(writer_quotes=['伪造的不存在引文']),
        lambda d: d['assessments'][0].update(writer_quotes=[]),
        lambda d: d['assessments'][0].update(reason=' '),
    ):
        invalid = json.loads(json.dumps(review))
        mutate(invalid)
        with pytest.raises(ValueError):
            check_visibility_response(json.dumps(invalid), visibility, writer)
    with pytest.raises(ValueError, match='writer prompt binding'):
        check_visibility_response(json.dumps(review), visibility, writer + '改动')
    from src.experiment import visibility_preflight as vp
    previous_contract_packet = vp.build_visibility_preflight(hidden_candidate, writer)
    with monkeypatch.context() as contract_patch:
        contract_patch.setattr(vp, 'REVIEW_RULES', vp.REVIEW_RULES + '\n改变披露口径')
        newer = vp.build_visibility_preflight(hidden_candidate, writer)
        assert newer['review_id'] != previous_contract_packet['review_id']
        with pytest.raises(ValueError, match='contract changed'):
            check_visibility_response(json.dumps(review), visibility, writer)
    assert probe.prepare_prose(gated, 'selected', hidden_text, json.dumps(review)) == 'VISIBILITY_REVIEW_REJECTED'
    assert not (gated / 'selected/prose_prompt.txt').exists()
    assert probe.prepare_prose(gated, 'selected', hidden_text) == 'VISIBILITY_REVIEW_REJECTED'

    # Compatible and inconclusive responses have distinct handoff outcomes; no calls.
    for verdict in ('compatible', 'inconclusive'):
        fresh = tmp_path / '.workspace_local' / verdict
        probe.prepare(case, fresh)
        probe.prepare_prose(fresh, 'selected', hidden_text)
        reply = json.loads(json.dumps(review))
        reply['assessments'][0].update(verdict=verdict, writer_quotes=[], reason='仅测离线控制流')
        expected_status = 'PROSE_PROMPT_PREPARED' if verdict == 'compatible' else 'VISIBILITY_REVIEW_REJECTED'
        assert probe.prepare_prose(fresh, 'selected', hidden_text, json.dumps(reply)) == expected_status
        assert (fresh / 'selected/prose_prompt.txt').exists() == (verdict == 'compatible')
        assert probe.prepare_prose(fresh, 'selected', hidden_text) == expected_status
        if verdict == 'compatible':
            assert (fresh / 'selected/prose_prompt.txt').read_text(encoding='utf-8') == writer
            handoff = json.loads((fresh / 'selected/handoff.json').read_text(encoding='utf-8'))
            assert handoff['visibility_review_id'] == visibility['review_id']
            assert handoff['visibility_contract_sha256'] == visibility['review_contract_sha256']
            assert handoff['visibility_scope'] == 'reader_disclosure_only'
            assert handoff['fact_support_evaluated'] is False
            changed = json.loads(hidden_text)
            changed['new_state']['hidden_information'] = ['另一条秘密']
            with pytest.raises(ValueError, match='frozen artifact differs'):
                probe.prepare_prose(fresh, 'selected', json.dumps(changed), json.dumps(reply))


    # Semantic-control scoring is tested with fixtures, never called model accuracy.
    from src.experiment.visibility_controls import materials, score, export
    controls = materials()
    empty = score({})
    assert (empty['planned'], empty['missing'], empty['accuracy_valid']) == (9, 9, None)
    replies = {}
    for row in controls:
        replies[row['case_id']] = json.dumps(dict(
            review_id=row['packet']['review_id'], assessments=[dict(
                item_id='hidden_001', verdict=row['expected'], reason='scoring fixture only',
                writer_quotes=[row['writer']] if row['expected'] == 'conflict' else [])]))
        assert row['rationale'] not in row['packet']['prompt']
    exact = score(replies)
    assert exact['correct'] == exact['valid'] == 9
    assert exact['false_release'] == exact['false_reject'] == 0
    assert exact['independent_reviewer_accuracy_established'] is False
    assert exact['disputed_legacy_labels'] == ['v03', 'v09']
    scope = materials('scope')
    assert len(scope) == 4
    assert score({}, 'scope')['missing'] == 4
    scope_replies = {r['case_id']: json.dumps(dict(review_id=r['packet']['review_id'],
        assessments=[dict(item_id='hidden_001', verdict=r['expected'], reason='scoring fixture only',
                          writer_quotes=[r['writer']] if r['expected']=='conflict' else [])])) for r in scope}
    assert score(scope_replies, 'scope')['correct'] == 4
    assert score(scope_replies, 'scope')['disputed_legacy_labels'] == []
    assert 's02' in score(scope_replies, 'scope')['post_run_label_notes']
    for case_id, verdict in [('v01', 'compatible'), ('v02', 'conflict')]:
        reply = json.loads(replies[case_id])
        reply['assessments'][0].update(verdict=verdict, writer_quotes=[
            next(r['writer'] for r in controls if r['case_id'] == case_id)])
        replies[case_id] = json.dumps(reply)
    replies['v03'] = '{}'
    del replies['v04']
    mixed = score(replies)
    assert (mixed['valid'], mixed['invalid'], mixed['missing']) == (7, 1, 1)
    assert (mixed['false_release'], mixed['false_reject'], mixed['correct']) == (1, 1, 5)
    with pytest.raises(ValueError, match='unknown'):
        score({'unexpected': '{}'})
    control_dir = tmp_path / '.workspace_local' / 'controls'
    export(control_dir)
    export(control_dir)
    (control_dir / 'prompts/v01.txt').write_text('altered', encoding='utf-8')
    with pytest.raises(ValueError, match='frozen artifact differs'):
        export(control_dir)


def test_full_state_not_injected():
    """V2：正文模型不该看到完整 State——Full State 渲染内容不进入 prompt."""
    from src.object_state.statemodel import StateModel, ThreadState, OffScreenProcess

    # Full State 里有 BACKGROUND/DORMANT 内容
    sm = StateModel(
        threads=[ThreadState(thread_id="t_bg", thread_type="官场线", label="陆平官场",
                             current_state="暗中角力")],
        offscreen=[OffScreenProcess(entity="夏晴", background_state="家庭生活")],
    )
    # 但传给 prompt 的只有 Chapter Packet（不含这些 BACKGROUND 项）
    packet = "本章应自然承载：\n- 恒通机芯谈判"
    prompt = _prompt(packet_context=packet)
    assert "陆平官场" not in prompt  # BACKGROUND 线程不在正文上下文
    assert "家庭生活" not in prompt  # offscreen 不在正文上下文
    # 更直接：即使把 Full State 渲染传进去（错误用法），也应能识别——此处验证正确用法不泄露

    import pytest
    from src.experiment.state_selection_probe import ResearchCase, build_bundle

    # Reject bad provenance and side-channel leakage before writing prompts.
    def rejected(change):
        raw = _research_case().model_dump(mode='json')
        change(raw)
        with pytest.raises(ValueError):
            build_bundle(ResearchCase.model_validate(raw))

    rejected(lambda d: d['sources'][0].update(chapter=2))
    rejected(lambda d: d['sources'][0].update(sha256='0' * 64))
    rejected(lambda d: d['threads'][0]['current'].update(start=1))
    rejected(lambda d: d['threads'][0]['thread'].update(current_state='没有来源的新事实'))
    rejected(lambda d: d['threads'][0]['thread'].update(recent_change='缺证据的变化'))
    rejected(lambda d: d['threads'][0].update(change={**d['threads'][0]['current'], 'source_id': 'missing'}))
    rejected(lambda d: d['threads'][0]['thread'].update(provenance='simulated'))
    rejected(lambda d: d['threads'][0]['thread'].update(last_chapter=2))
    rejected(lambda d: d['threads'][0]['thread'].update(near_payoff=True))
    rejected(lambda d: d['threads'].append(d['threads'][0]))
    rejected(lambda d: d['sources'].append(d['sources'][0]))
    rejected(lambda d: d.update(scene=d['threads'][2]['current']))
    rejected(lambda d: d['threads'][1].update(can_reveal=False))  # identical arms
    rejected(lambda d: d.update(max_selected=-1))
