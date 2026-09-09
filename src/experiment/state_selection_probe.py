"""Offline research entry: grounded thread-state ablation, then prose handoff.

Run with ``python -m src.experiment.state_selection_probe --help``.
This module never calls a model or commits narrative state. Its JSON case is a
research input, not a new production StateModel. Only exact source quotations
are admitted in this first slice; trigger/visibility annotations remain supplied
experimental assumptions, not facts proven by a matching quotation.
"""

import argparse
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.object_state import FactLedger, ForeshadowGraph, NarrativeState
from src.object_state.statemodel import CompressionLevel, Provenance, StateModel, ThreadState
from src.workflow_action.candidate_pool import Candidate, build_candidate_pool
from src.workflow_action.context_firewall import build_chapter_packet
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.narrative_selector import SelectionResult, select_candidates, suppress_overreach
from src.workflow_action import prose
from src.experiment.visibility_preflight import build_visibility_preflight, check_visibility_response

ROOT = Path(__file__).resolve().parents[2]
ARMS = ('direct', 'selected')
ENGINE_ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ('src/experiment/state_selection_probe.py', 'src/workflow_action/candidate_pool.py',
                'src/workflow_action/narrative_selector.py', 'src/workflow_action/context_firewall.py',
                'src/workflow_action/continuation.py', 'src/workflow_action/prose.py',
                'src/experiment/visibility_preflight.py', 'src/object_state/narrativestate.py',
                'src/workflow_action/json_repair.py')


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Source(StrictModel):
    source_id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=60000)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class Quote(StrictModel):
    source_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    exact: str = Field(min_length=1)


class GroundedThread(StrictModel):
    thread: ThreadState
    current: Quote
    change: Quote | None = None
    can_reveal: bool = False


class ResearchCase(StrictModel):
    case_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    source_group: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    cutoff_chapter: int = Field(ge=1)
    sources: list[Source] = Field(min_length=1)
    scene: Quote
    threads: list[GroundedThread] = Field(min_length=1)
    canon_required: list[Quote] = Field(default_factory=list, max_length=6)
    necessary_relations: list[Quote] = Field(default_factory=list)
    max_selected: int = Field(default=2, ge=0, le=6)
    target_chapter_chars: int = Field(default=1200, ge=200, le=3000)


def validate_evidence(case: ResearchCase) -> None:
    sources = {s.source_id: s for s in case.sources}
    if len(sources) != len(case.sources):
        raise ValueError('duplicate source_id')
    for source in sources.values():
        if source.chapter > case.cutoff_chapter:
            raise ValueError('future source exceeds cutoff_chapter')
        if sha(source.text) != source.sha256:
            raise ValueError('source hash mismatch')

    def check(q: Quote):
        source = sources.get(q.source_id)
        if source is None or q.start >= q.end or q.end > len(source.text) or source.text[q.start:q.end] != q.exact:
            raise ValueError('quote source/span mismatch')

    for quote in [case.scene, *case.canon_required, *case.necessary_relations]:
        check(quote)
    ids = set()
    for item in case.threads:
        t = item.thread
        if t.thread_id in ids:
            raise ValueError('duplicate thread_id')
        ids.add(t.thread_id)
        check(item.current)
        if t.current_state != item.current.exact:
            raise ValueError('current_state must equal the cited quotation in this slice')
        if t.provenance != Provenance.CANON:
            raise ValueError('inferred/simulated thread text is outside this extractive slice')
        if t.near_payoff:
            raise ValueError('near_payoff needs semantic evidence; outside this slice')
        if t.last_chapter is not None and t.last_chapter > case.cutoff_chapter:
            raise ValueError('future thread timestamp')
        if item.change is not None:
            check(item.change)
        if t.recent_change:
            if item.change is None:
                raise ValueError('recent_change has no evidence')
            if t.recent_change != item.change.exact:
                raise ValueError('recent_change must equal its quotation')


def common_state(case: ResearchCase) -> NarrativeState:
    # No raw CharacterModel, FactLedger, hidden_information or offstage side channel.
    return NarrativeState(state_id=f'{case.case_id}_start', current_time='前文结束时',
                          current_location='沿用前文场景', current_situation=case.scene.exact)


def build_bundle(case: ResearchCase) -> dict[str, str]:
    validate_evidence(case)
    visible = [x for x in case.threads if x.can_reveal and x.thread.compression != CompressionLevel.ARCHIVED]
    sm = StateModel(last_chapter=case.cutoff_chapter,
                    threads=[x.thread.model_copy(deep=True) for x in visible])
    pool = build_candidate_pool(sm, reader_knowledge={x.thread.label for x in visible})
    evidence = {f'c_{x.thread.thread_id}': x.current for x in visible}
    for candidate in pool.candidates:
        candidate.evidence = json_text(evidence[candidate.candidate_id].model_dump())
    selected = suppress_overreach(select_candidates(pool, sm, max_selected=case.max_selected))
    direct = SelectionResult()
    direct.selected = [Candidate(candidate_id=f'c_{x.thread.thread_id}', source_thread=x.thread.label,
                                 current_change=x.thread.current_state, trigger_source='direct_state',
                                 reader_knows=True, provenance=x.thread.provenance,
                                 evidence=json_text(x.current.model_dump())) for x in visible]
    files = {'case.json': json_text(case.model_dump(mode='json'))}
    trace = {'schema': 'state-selection-research-v1', 'cutoff_chapter': case.cutoff_chapter,
             'source_group': case.source_group, 'source_hashes': {s.source_id: s.sha256 for s in case.sources},
             'interpretation': 'guarded direct thread state versus existing selector; not full State V1/V2 quality',
             'unproven_annotations': ['trigger relevance', 'compression', 'can_reveal'],
             'arms': {}, 'new_model_calls': 0, 'production_authorization': False}
    common_prompts = []
    hidden = [x.current.exact for x in case.threads if not x.can_reveal]
    for arm, selection in [('direct', direct), ('selected', selected)]:
        packet = build_chapter_packet(selection, chapter=case.cutoff_chapter + 1,
                                      canon_required=[q.exact for q in case.canon_required],
                                      necessary_relations=[q.exact for q in case.necessary_relations])
        # Both arms use exactly the same neutral wording: a larger set is not an order to write every item.
        context = packet.render().replace('本章应自然承载：', '可参考的线程状态（不要求全部写入正文）：')
        prompt = ContinueUnit().build_prompt(common_state(case), [], FactLedger(entries=[]), ForeshadowGraph(entries=[]),
                                            workspec_context='依据前文继续故事，人物行动应产生可理解的后果。',
                                            excerpt_context=case.scene.exact, packet_context=context)
        if any(text in prompt for text in hidden):
            raise ValueError('hidden thread text re-entered through common context')
        files[f'packet_{arm}.txt'] = context
        files[f'continue_{arm}.txt'] = prompt
        trace['arms'][arm] = {'selected_ids': selection.ids('selected'), 'background_ids': selection.ids('background'),
                              'dormant_ids': selection.ids('dormant'), 'excluded_alive': pool.excluded_alive if arm == 'selected' else [],
                              'prompt_chars': len(prompt), 'prompt_sha256': sha(prompt)}
        common_prompts.append(prompt.replace(context, '<STATE_PACKET>', 1) if context else prompt)
    if common_prompts[0] != common_prompts[1]:
        raise ValueError('arms differ outside state packet (or packet is empty); invalid comparison')
    if files['continue_direct.txt'] == files['continue_selected.txt']:
        raise ValueError('identical arms: no selection intervention to test')
    withheld = [c for c in direct.selected if c.candidate_id not in selected.ids('selected')
                and c.current_change not in files['continue_selected.txt']]
    if not withheld:
        raise ValueError('no effective exposure contrast: omitted states remain in shared context')
    trace['withheld_from_selected_prompt'] = [c.candidate_id for c in withheld]
    trace['common_prompt_sha256'] = sha(common_prompts[0])
    files['trace.json'] = json_text(trace)
    return files


def private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / '.workspace_local').resolve()):
        raise ValueError('research output must stay under repository .workspace_local')
    return resolved


def write_frozen(directory: Path, files: dict[str, str]) -> None:
    directory = private_path(directory)
    # Check all collisions before any write. Existing matching files are idempotent.
    for name, text in files.items():
        p = directory / name
        if p.exists() and p.read_bytes() != text.encode('utf-8'):
            raise ValueError(f'frozen artifact differs: {name}; use a new output directory')
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        p = directory / name
        if not p.exists():
            with p.open('xb') as stream:
                stream.write(text.encode('utf-8'))


def prepare(case: ResearchCase, directory: Path) -> None:
    files = build_bundle(case)
    manifest = {'schema': 'state-selection-bundle-v1', 'case_id': case.case_id,
                'files': {name: sha(text) for name, text in files.items()},
                'entry_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'engine_sha256': {p: hashlib.sha256((ENGINE_ROOT / p).read_bytes()).hexdigest() for p in ENGINE_FILES},
                'status': 'PROMPTS_PREPARED_NO_MODEL_CALLS'}
    files['manifest.json'] = json_text(manifest)
    write_frozen(directory, files)


def prepare_prose(directory: Path, arm: str, response_text: str,
                  visibility_response_text: str | None = None) -> str:
    directory = private_path(directory)
    if arm not in ARMS:
        raise ValueError('unknown arm')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    current_engine = {p: hashlib.sha256((ENGINE_ROOT / p).read_bytes()).hexdigest() for p in ENGINE_FILES}
    if manifest.get('engine_sha256') != current_engine:
        raise ValueError('research implementation changed; prepare a new bundle')
    expected_names = {'case.json', 'trace.json', *(f'{kind}_{a}.txt' for kind in ('packet', 'continue') for a in ARMS)}
    if set(manifest['files']) != expected_names:
        raise ValueError('bundle artifact list mismatch')
    for name, expected in manifest['files'].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'bundle hash mismatch: {name}')
    case = ResearchCase.model_validate_json((directory / 'case.json').read_text(encoding='utf-8'))
    rebuilt = build_bundle(case)
    if any(sha(text) != manifest['files'][name] for name, text in rebuilt.items()):
        raise ValueError('prompt implementation changed; prepare a new bundle')
    plot, new_state, new_facts, gaps = ContinueUnit().parse_response(response_text)
    if plot.input_state_ref != common_state(case).state_id or plot.output_state_ref != new_state.state_id:
        raise ValueError('response state references do not match this case')
    if any(x.current.exact in response_text for x in case.threads if not x.can_reveal):
        raise ValueError('response contains hidden thread quotation')
    packet = rebuilt[f'packet_{arm}.txt']
    prompt = prose.build_prompt(plot, new_state, excerpt_context=case.scene.exact + '\n\n' + packet,
                                target_chapter_chars=case.target_chapter_chars)
    visibility_result = None
    if new_state.hidden_information:
        candidate = dict(plotunit=plot.model_dump(mode='json'), new_state=new_state.model_dump(mode='json'),
                         new_facts=new_facts, confidence_gaps=gaps)
        visibility = build_visibility_preflight(candidate, prompt)
        write_frozen(directory / arm, {'continue_response.json': response_text,
                     'writer_prompt_candidate.txt': prompt,
                     'visibility_preflight.json': json_text({k: v for k, v in visibility.items() if k != 'prompt'}),
                     'visibility_prompt.txt': visibility['prompt']})
        saved_review = directory / arm / 'visibility_response.json'
        if visibility_response_text is None and saved_review.exists():
            visibility_response_text = saved_review.read_text(encoding='utf-8')
        if visibility_response_text is None:
            return 'VISIBILITY_REVIEW_REQUIRED'
        visibility_result = check_visibility_response(visibility_response_text, visibility, prompt)
        write_frozen(directory / arm, {'visibility_response.json': visibility_response_text,
                                      'visibility_result.json': json_text(visibility_result)})
        if not visibility_result['compatible']:
            return 'VISIBILITY_REVIEW_REJECTED'
    elif visibility_response_text is not None:
        raise ValueError('visibility response supplied without review obligations')
    write_frozen(directory / arm, {'continue_response.json': response_text, 'prose_prompt.txt': prompt,
                                   'handoff.json': json_text({'response_sha256': sha(response_text),
                                                             'continue_prompt_sha256': manifest['files'][f'continue_{arm}.txt'],
                                                             'prose_prompt_sha256': sha(prompt), 'confidence_gaps': gaps,
                                                             'status': 'PROSE_PROMPT_ONLY_NO_STATE_COMMIT',
                                                             'usage_receipt': None, 'quality_verdict': None,
                                                             **({'visibility_review_id': visibility_result['review_id'],
                                                                 'visibility_contract_sha256': visibility_result['review_contract_sha256'],
                                                                 'visibility_scope': 'reader_disclosure_only',
                                                                 'fact_support_evaluated': False,
                                                                 'visibility_response_sha256': sha(visibility_response_text)}
                                                                if visibility_result else {})})})
    return 'PROSE_PROMPT_PREPARED'


def main() -> int:
    parser = argparse.ArgumentParser(description='离线 State 选择实验入口：来源校验、两臂提示、正文提示交接；不调用模型')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('prose')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--response', type=Path, required=True)
    p.add_argument('--visibility-response', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare(ResearchCase.model_validate_json(args.case.read_text(encoding='utf-8-sig')), args.output)
        else:
            status = prepare_prose(args.bundle, args.arm, args.response.read_text(encoding='utf-8-sig'),
                args.visibility_response.read_text(encoding='utf-8-sig') if args.visibility_response else None)
            if status != 'PROSE_PROMPT_PREPARED':
                print(f'{status}; model_calls=0; state_commits=0')
                return 3
    except (ValueError, OSError, KeyError) as exc:
        # Do not dump Pydantic input values or private novel content to terminal logs.
        if isinstance(exc, ValidationError):
            detail = [{'field': list(e['loc']), 'type': e['type']} for e in exc.errors()]
        elif isinstance(exc, ValueError):
            detail = str(exc)
        else:
            detail = type(exc).__name__
        print(json.dumps({'status': 'RESEARCH_INPUT_REJECTED', 'detail': detail}, ensure_ascii=False))
        return 2
    print('RESEARCH_PROMPTS_PREPARED; model_calls=0; state_commits=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
