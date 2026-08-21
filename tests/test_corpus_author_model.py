from pathlib import Path
import hashlib
import json
import re
from copy import deepcopy

import pytest

from src.object_state.corpusauthormodel import Author, SelectionPattern
from src.workflow_action.corpus_author_model import (
    _DILEMMA_LEXICON,
    _balanced_ranked_pool,
    _bounded_work_quotas,
    _stratified_work_quotas,
    extract_authors,
    inspect_corpus,
    retrieve_balanced_dilemma_candidates,
    retrieve_dilemma_candidates,
    run,
)
from scripts.validate_author_personality_run import validate_personality_run


def test_author_requires_chapter_evidence(tmp_path: Path):
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="neutral pattern",
            confidence=0.5,
            chapter_evidence=[],
        )

    run_dir = tmp_path / "synthetic_personality_run"
    run_dir.mkdir()
    try:
        chapter_indexes = [10, 20, 35, 50]
        headers = "\n".join(
            f"--- chapter evidence sample {chapter} (work-{i:03d}, {'early' if i % 2 else 'late'}) ---"
            for i, chapter in enumerate(chapter_indexes, 1)
        )
        sample_text = "A sufficiently long neutral sample sentence for overlap checks."
        candidate_chapter = 60
        candidate_work = "work-003"
        candidate_stage = "middle"
        candidate_text = "A sufficiently long neutral discovery sample sentence for overlap checks."
        candidate_header = (
            f"--- dilemma discovery candidate {candidate_chapter} "
            f"({candidate_work}, {candidate_stage}) ---"
        )
        prompt = {"prompt": headers + "\n" + sample_text + "\n" + candidate_header + "\n" + candidate_text}
        response = {
            "selection_patterns": [
                {
                    "pattern_id": f"pattern-{i:03d}",
                    "statement": "neutral pattern",
                    "confidence": 0.9,
                    "chapter_evidence": [{"chapter_index": i, "metric": "signal", "value": "stable"}],
                }
                for i in range(1, 5)
            ]
        }
        kinds = ["signature_choice", "signature_refusal", "sacrifice_pattern", "obsession"]
        sidecar = {
            "schema_version": "1",
            "author_id": "subject-test",
            "run_id": "run-test",
            "source_generation": "synthetic",
            "claims": [
                {
                    "claim_id": f"claim-{i:03d}",
                    "kind": kind,
                    "statement": "neutral claim",
                    "status": "candidate",
                    "scope": "author_global",
                    "confidence": 0.9,
                    "supporting_evidence": [
                        {"chapter_index": 10, "work_slot": "work-001", "stage": "early", "metric": "signal", "value": "stable"},
                        {"chapter_index": 20, "work_slot": "work-002", "stage": "late", "metric": "signal", "value": "stable"},
                    ],
                    "counterevidence": ["neutral counterevidence"],
                }
                for i, kind in enumerate(kinds, 1)
            ],
            "counterfactual_pairs": [],
            "uniqueness": {"status": "not_run", "transferable_author_count": None},
        }

        def write_run(current_response=response, current_sidecar=sidecar):
            (run_dir / "corpus_author_model_prompt.txt").write_text(json.dumps(prompt), encoding="utf-8")
            (run_dir / "corpus_author_model_response.json").write_text(json.dumps(current_response), encoding="utf-8-sig")
            (run_dir / "personality_sidecar.json").write_text(json.dumps(current_sidecar), encoding="utf-8")
            return validate_personality_run(run_dir, "subject-test", "run-test")

        assert write_run() == []
        candidate_sidecar = deepcopy(sidecar)
        candidate_sidecar["claims"][0]["supporting_evidence"].append(
            {
                "chapter_index": candidate_chapter,
                "work_slot": candidate_work,
                "stage": candidate_stage,
                "metric": "signal",
                "value": "stable",
            }
        )
        assert write_run(response, candidate_sidecar) == []
        wrong_candidate_sidecar = deepcopy(candidate_sidecar)
        wrong_candidate_sidecar["claims"][0]["supporting_evidence"][-1]["work_slot"] = "work-004"
        wrong_candidate_sidecar["claims"][0]["supporting_evidence"][-1]["stage"] = "late"
        assert "supporting_evidence_anchor" in write_run(response, wrong_candidate_sidecar)
        candidate_overlap_sidecar = deepcopy(candidate_sidecar)
        candidate_overlap_sidecar["claims"][0]["statement"] = candidate_text
        assert "verbatim_sample_overlap" in write_run(response, candidate_overlap_sidecar)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][0]["extra"] = True
        assert "pattern_keys" in write_run(mutated_response)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][0]["chapter_evidence"][0]["extra"] = True
        assert "evidence_keys" in write_run(mutated_response)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][0]["chapter_evidence"] = []
        assert "evidence_shape" in write_run(mutated_response)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][1]["pattern_id"] = mutated_response["selection_patterns"][0]["pattern_id"]
        assert "pattern_id_unique" in write_run(mutated_response)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][0]["statement"] = "neutral author"
        assert "forbidden_response_token" in write_run(mutated_response)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["statement"] = "neutral author"
        assert "forbidden_sidecar_token" in write_run(response, mutated_sidecar)
        mutated_response = deepcopy(response)
        mutated_response["selection_patterns"][0]["statement"] = sample_text
        assert "verbatim_sample_overlap" in write_run(mutated_response)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["kind"] = "other"
        assert "claim_kinds" in write_run(response, mutated_sidecar)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["confidence"] = 0.84
        assert "claim_confidence" in write_run(response, mutated_sidecar)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["supporting_evidence"][0]["stage"] = "late"
        assert "supporting_evidence_anchor" in write_run(response, mutated_sidecar)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["supporting_evidence"] = [
            {"chapter_index": 10, "work_slot": "work-001", "stage": "early", "metric": "signal", "value": "stable"},
            {"chapter_index": 35, "work_slot": "work-001", "stage": "early", "metric": "signal", "value": "stable"},
        ]
        assert {"supporting_evidence_works", "supporting_evidence_stages"}.issubset(
            write_run(response, mutated_sidecar)
        )
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["claims"][0]["status"] = "confirmed"
        assert "claim_status" in write_run(response, mutated_sidecar)
        mutated_sidecar = deepcopy(sidecar)
        mutated_sidecar["uniqueness"] = {"status": "measured", "transferable_author_count": 1}
        assert "uniqueness" in write_run(response, mutated_sidecar)
        # D5: the same BOM response the validator accepts must also materialize through run().
        corpus = tmp_path / "corpus"
        (corpus / "chapters").mkdir(parents=True)
        (corpus / "chapters" / "chapter_001.txt").write_text("人物突然转身。", encoding="utf-8")
        materialized = tmp_path / "materialized"
        assert run(corpus, materialized)["status"] == "waiting"
        response_path = materialized / "corpus_author_model_response.json"
        response_path.write_text(json.dumps(response), encoding="utf-8-sig")
        assert response_path.read_bytes().startswith(b"\xef\xbb\xbf"), "utf-8-sig write must carry a real BOM"
        assert run(corpus, materialized)["status"] == "materialized"
    finally:
        for path in run_dir.iterdir():
            path.unlink()
        run_dir.rmdir()


def test_author_schema_forbids_identity_and_extra_fields():
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="author prefers this",
            confidence=0.5,
            chapter_evidence=[{"chapter_index": 1, "metric": "signal", "value": "1"}],
        )
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="neutral pattern",
            confidence=0.5,
            chapter_evidence=[{"chapter_index": 1, "metric": "signal", "value": "1", "extra": 1}],
        )


def test_metadata_workflow_waits_then_materializes_without_persisting_samples(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "chapters").mkdir(parents=True)
    (corpus / "chapters" / "chapter_001.txt").write_text("人物突然转身。", encoding="utf-8")
    (corpus / "chapters" / "chapter_002.txt").write_text("“他说道：继续。”", encoding="utf-8")
    (corpus / "metrics.json").write_text(json.dumps({"metrics": {"mean_length": 10}}), encoding="utf-8")
    output = tmp_path / "out"
    first = run(corpus, output)
    assert first["status"] == "waiting"
    prompt = (output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8")
    assert "chapter evidence sample" in prompt
    response = output / "corpus_author_model_response.json"
    response.write_text(
        json.dumps(
            {
                "selection_patterns": [
                    {
                        "pattern_id": "pattern-001",
                        "statement": "turning points cluster near chapter endings",
                        "confidence": 0.8,
                        "chapter_evidence": [
                            {"chapter_index": 1, "metric": "hook_signal_rate", "value": "1"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    second = run(corpus, output)
    assert second["status"] == "materialized"
    model_path = output / "author_models" / "corpus-author-a.json"
    model = Author.model_validate_json(model_path.read_text(encoding="utf-8"))
    assert model.corpus_size["chapter_files"] == 2
    assert model.method_layer_stats["dialogue_ratio"] > 0
    assert "突然转身" not in model_path.read_text(encoding="utf-8")
    before = model_path.read_bytes()
    assert run(corpus, output)["status"] == "materialized"
    assert model_path.read_bytes() == before


def test_deep_sampling_is_uniform_and_preserves_v1_generation(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "chapters").mkdir(parents=True)
    for index in range(1, 11):
        (corpus / "chapters" / f"chapter_{index:03d}.txt").write_text(
            f"第{index}章。", encoding="utf-8"
        )
    output = tmp_path / "out"
    run(corpus, output)
    response = output / "corpus_author_model_response.json"
    response.write_text(
        json.dumps(
            {
                "selection_patterns": [
                    {
                        "pattern_id": "pattern-001",
                        "statement": "sampled pacing changes across the arc",
                        "confidence": 0.8,
                        "chapter_evidence": [
                            {"chapter_index": 1, "metric": "signal", "value": "sample"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    run(corpus, output)
    response.unlink()

    waiting = run(corpus, output, sample_chapters=5)
    assert waiting["status"] == "waiting"
    prompt_payload = json.loads((output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8"))
    prompt = prompt_payload["prompt"]
    assert prompt.count("chapter evidence sample") == 5
    assert '"sampled_chapters": 5' in prompt
    # legacy chapters/ 模式：旧格式样本头字节级保持（首/中/末），无 work slot
    assert "--- chapter evidence sample 1 ---" in prompt
    assert "--- chapter evidence sample 5 ---" in prompt
    assert "--- chapter evidence sample 10 ---" in prompt
    assert "(work-" not in prompt
    history = output / "author_models" / "corpus-author-a.generations.json"
    assert history.exists()
    assert history.read_text(encoding="utf-8").count('"extraction_generation": "deterministic-metadata-v1"') == 1

    response.write_text(
        json.dumps(
            {
                "selection_patterns": [
                    {
                        "pattern_id": "pattern-001",
                        "statement": "sampled pacing changes across the arc",
                        "confidence": 0.8,
                        "chapter_evidence": [
                            {"chapter_index": 1, "metric": "signal", "value": "sample"},
                            {"chapter_index": 10, "metric": "turn", "value": "sample"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    materialized = run(corpus, output, sample_chapters=5)
    assert materialized["model"]["extraction_generation"] == "deep-v2"
    assert materialized["model"]["corpus_size"]["sampled_chapters"] == 5


def test_batch_extraction_supports_multiple_author_instances(tmp_path: Path):
    roots = []
    for index in range(2):
        root = tmp_path / f"corpus-{index}"
        (root / "chapters").mkdir(parents=True)
        (root / "chapters" / "chapter_001.txt").write_text("一章。", encoding="utf-8")
        roots.append(root)
    result = extract_authors(roots, ["author-a", "author-b"])
    assert [item["author_id"] for item in result] == ["author-a", "author-b"]
    assert result[0]["source_digest"] != ""


def test_directory_of_full_novels_expands_chapters_and_stratified_sampling(tmp_path: Path):
    """两本完整小说 TXT（各 3 章，无 chapters/ 目录）应展开为 6 章；
    3 个样本按 source work 分层（quota [2, 1]）：第一本首末两章有阶段证据，
    第二本至少 1 个代表样本。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # 第一本：3 章（虚构短文本；alpha_book < beta_book，保证路径排序确定）
    (corpus / "alpha_book.txt").write_text(
        "第1章 启程\n林舟把旧怀表放进衣袋，晨雾还未散尽。\n"
        "第2章 风暴\n桅杆折断的夜里，林舟听见了海底的钟声。\n"
        "第3章 灯台\n灯台守夜人递来一封信，落款是十年前的名字。\n",
        encoding="utf-8",
    )
    # 第二本：3 章（虚构短文本）
    (corpus / "beta_book.txt").write_text(
        "第1章 雨夜\n沈砚在雨夜的站台等最后一班车。\n"
        "第2章 档案\n档案馆的铁柜里躺着三张空白车票。\n"
        "第3章 回声\n沈砚在旧剧场听见自己的声音提前响起。\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    waiting = run(corpus, output, sample_chapters=3)
    assert waiting["status"] == "waiting"
    prompt_payload = json.loads((output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8"))
    prompt = prompt_payload["prompt"]
    # 展开后总章数 = 2 本 × 3 章
    assert '"chapter_files": 6' in prompt
    assert '"sampled_chapters": 3' in prompt
    # 第一本 quota 2 保持不变；全局补齐 middle 时以第 2 章替换重复 early。
    assert "桅杆折断" in prompt, "语料具备 middle 时全局必须补齐该阶段"
    assert "灯台守夜人" in prompt, "第一本第 3 章必须被抽样"
    # 第二本 quota 1：代表样本 = 第 1 章
    assert "站台" in prompt, "第二本必须有样本"
    assert "旧剧场" not in prompt, "第二本 quota 1 只抽第 1 章"
    # 中性 work slot + 阶段 + 全局编号（隐私安全来源分组）
    assert "chapter evidence sample 2 (work-001, middle)" in prompt
    assert "chapter evidence sample 3 (work-001, late)" in prompt
    assert "chapter evidence sample 4 (work-002, early)" in prompt
    assert "alpha_book" not in prompt
    assert "beta_book" not in prompt
    # dilemma 候选检索（opt-in）：确定性 + 有界唯一 + 仅 score>0 + 中性 work/stage 轮转
    def book(prefix, marks):
        return "\n".join(
            f"第{i}章 {prefix}{i}\n" + (f"{prefix}{i}。" if i not in marks else marks[i])
            for i in range(1, 9)
        )

    late_phrase = "拒绝选择代价执念"
    late_a = "前置内容。" * 400 + late_phrase * 10 + "。" * 20
    late_b = "乙二独有标记。" + "前置内容。" * 400 + late_phrase * 8
    assert late_a.index(late_phrase) > 1600 and late_b.index(late_phrase) > 1600
    assert late_a.count(late_phrase) == 10
    marks_a = {4: late_a, 5: "拒绝选择代价执念" * 9}  # 得分 40 / 36
    marks_b = {2: late_b}  # 得分 32
    (corpus / "alpha_book.txt").write_text(book("甲", marks_a), encoding="utf-8")
    (corpus / "beta_book.txt").write_text(book("乙", marks_b), encoding="utf-8")
    selected = {0, 7, 8, 15}  # 已抽样：alpha 第 1/8 章 + beta 第 1/8 章
    a, sa = retrieve_dilemma_candidates(corpus, selected=selected, requested=2)
    b, sb = retrieve_dilemma_candidates(corpus, selected=selected, requested=2)
    assert (sa, sb) == (0, 0)
    assert [(c.chapter_index, c.work_id, c.stage) for c in a] == [(c.chapter_index, c.work_id, c.stage) for c in b]
    # 纯全局 top-2 会两票都给 work-001（40、36）；round-robin 把第二票给 work-002（32）
    assert [(c.chapter_index, c.work_id, c.stage) for c in a] == [
        (4, "work-001", "middle"),
        (10, "work-002", "early"),
    ]
    assert all(len(candidate.text) <= 1600 for candidate in a)
    assert all(
        any(pattern.search(candidate.text) for pattern in _DILEMMA_LEXICON.values())
        for candidate in a
    )
    assert "拒绝" in a[0].text and "选择" in a[0].text
    assert "拒绝" in a[1].text and "选择" in a[1].text
    # 有界 + 仅 score>0：eligible 只有 3 章，超预算也不零命中凑数
    all_c, all_short = retrieve_dilemma_candidates(corpus, selected=selected, requested=100)
    assert all_short == 97 and len(all_c) == 3
    assert {c.chapter_index for c in all_c} == {4, 5, 10}
    assert not ({c.chapter_index - 1 for c in all_c} & selected), "候选必须是未选章节"
    from src.novel_cli import build_parser
    args = build_parser().parse_args(
        [
            "corpus-author-model", "--input", ".", "--output-dir", ".",
            "--dilemma-retrieval", "--balanced-dilemma-retrieval",
            "--dilemma-candidates", "4",
        ]
    )
    assert args.dilemma_retrieval is True and args.dilemma_candidates == 4
    assert args.balanced_dilemma_retrieval is True
    ranked = _balanced_ranked_pool([
        (20, 1, 1, ("work-001", "middle")),
        (10, 1, 1, ("work-001", "early")),
        (11, 1, 1, ("work-002", "early")),
    ])
    assert [item[0] for item in ranked] == [10, 11, 20]

    # balanced 模式独立于旧 aggregate 路径：稀缺类别先认领、多标签全局去重，
    # 且围绕被指派类别命中截取，而不是被更早的其他类别命中抢走窗口。
    balanced = tmp_path / "balanced"
    balanced.mkdir()
    late_fixation = "选择。" + "前置内容。" * 400 + "执念。"
    balanced_texts = [
        "选择。", "选择。", "拒绝。", "代价。", late_fixation,
    ]
    (balanced / "work.txt").write_text(
        "".join(
            f"第{index}章 合成{index}\n{text}\n"
            for index, text in enumerate(balanced_texts, 1)
        ),
        encoding="utf-8",
    )
    one, one_meta = retrieve_balanced_dilemma_candidates(
        balanced, selected=set(), requested=1
    )
    assert [candidate.discovery_category for candidate in one] == ["refusal"]
    assert one_meta["categories"]["refusal"]["target"] == 1
    two, _ = retrieve_balanced_dilemma_candidates(balanced, selected=set(), requested=2)
    assert {candidate.discovery_category for candidate in two} == {"refusal", "cost"}
    three, _ = retrieve_balanced_dilemma_candidates(balanced, selected=set(), requested=3)
    assert {candidate.discovery_category for candidate in three} == {
        "refusal", "cost", "fixation"
    }
    four, four_meta = retrieve_balanced_dilemma_candidates(
        balanced, selected=set(), requested=4
    )
    assert len(four) == len({candidate.chapter_index for candidate in four}) == 4
    assert {candidate.discovery_category for candidate in four} == set(_DILEMMA_LEXICON)
    assert all(four_meta["categories"][kind]["target"] == 1 for kind in _DILEMMA_LEXICON)
    assert [candidate.work_id for candidate in four] == ["work-001"] * 4
    fixation = next(candidate for candidate in four if candidate.discovery_category == "fixation")
    assert "执念" in fixation.text and len(fixation.text) <= 1600
    out_balanced = tmp_path / "out-balanced"
    run(
        balanced,
        out_balanced,
        sample_chapters=1,
        dilemma_retrieval=True,
        dilemma_candidates=4,
        balanced_dilemma_retrieval=True,
    )
    balanced_prompt = json.loads(
        (out_balanced / "corpus_author_model_prompt.txt").read_bytes()
    )["prompt"]
    balanced_block = balanced_prompt.split("--- dilemma discovery candidates ---", 1)[1]
    assert '"mode": "balanced"' in balanced_block
    assert balanced_block.count("Discovery category:") == 4
    assert re.search(r"\b(pass|confidence|verdict|score)\b", balanced_block, re.I) is None


def test_stratified_sampling_covers_short_books_when_lengths_unequal(tmp_path: Path):
    """两本长度极不均衡（20 章长书 + 2 章短书）、4 个样本：
    分层抽样让两本都被覆盖且各自有阶段证据；全局均匀会被长书支配。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # 长书 20 章（虚构短文本；long_book < short_book 按路径排序在前）
    (corpus / "long_book.txt").write_text(
        "".join(f"第{i}章 长{i}\n长书独有标记{i}。\n" for i in range(1, 21)),
        encoding="utf-8",
    )
    # 短书 2 章
    (corpus / "short_book.txt").write_text(
        "第1章 短一\n短书独有标记1。\n第2章 短二\n短书独有标记2。\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    waiting = run(corpus, output, sample_chapters=4)
    assert waiting["status"] == "waiting"
    prompt_payload = json.loads((output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8"))
    prompt = prompt_payload["prompt"]
    assert '"chapter_files": 22' in prompt
    assert '"sampled_chapters": 4' in prompt
    # 长书 quota 2 保持不变；全局补齐 middle 时替换重复 early。
    assert "长书独有标记8" in prompt, "语料具备 middle 时全局必须补齐该阶段"
    assert "长书独有标记20" in prompt, "长书第 20 章必须被抽样"
    # 短书 quota 2：两章全被覆盖（短书全部章节都有代表）
    assert "短书独有标记1" in prompt, "短书第 1 章必须被抽样"
    assert "短书独有标记2" in prompt, "短书第 2 章必须被抽样"
    # 中性 work slot + 阶段 + 全局编号，且无源文件名
    assert "chapter evidence sample 8 (work-001, middle)" in prompt
    assert "chapter evidence sample 20 (work-001, late)" in prompt
    assert "chapter evidence sample 21 (work-002, early)" in prompt
    assert "chapter evidence sample 22 (work-002, late)" in prompt
    assert "long_book" not in prompt
    assert "short_book" not in prompt


def test_stratified_work_quotas_properties():
    """19 本 / 36 样本：每本至少 1，余数 17 均分给前 17 本，总配额 = 36。"""
    quotas = _stratified_work_quotas(19, 36)
    assert len(quotas) == 19
    assert all(quota >= 1 for quota in quotas)
    assert sum(quotas) == 36
    assert quotas.count(2) == 17
    assert quotas.count(1) == 2
    # sample_chapters < work_count：均匀选作、每作 1 个代表样本
    sparse = _stratified_work_quotas(5, 2)
    assert sum(sparse) == 2
    assert [index for index, quota in enumerate(sparse) if quota] == [0, 4]


def test_prompt_uses_neutral_work_slots_without_source_names(tmp_path: Path):
    """跨作品稳定性：prompt 样本按中性 work-001/work-002 与阶段（early/late）分组，
    保留全局 chapter evidence index，且绝不暴露源文件名/书名。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha_book.txt").write_text(
        "第1章 卷一\n独有标记甲一。\n第2章 卷二\n独有标记甲二。\n",
        encoding="utf-8",
    )
    (corpus / "beta_book.txt").write_text(
        "第1章 卷乙一\n独有标记乙一。\n第2章 卷乙二\n独有标记乙二。\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    waiting = run(corpus, output, sample_chapters=4)
    assert waiting["status"] == "waiting"
    prompt_payload = json.loads((output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8"))
    prompt = prompt_payload["prompt"]
    # 不同中性 work slot + 各自阶段标记，且保留全局 chapter evidence index
    assert "chapter evidence sample 1 (work-001, early)" in prompt
    assert "chapter evidence sample 2 (work-001, late)" in prompt
    assert "chapter evidence sample 3 (work-002, early)" in prompt
    assert "chapter evidence sample 4 (work-002, late)" in prompt
    # 无源文件名/书名
    assert "alpha_book" not in prompt
    assert "beta_book" not in prompt
    # 各自阶段证据文本在场
    assert "独有标记甲一" in prompt and "独有标记甲二" in prompt
    assert "独有标记乙一" in prompt and "独有标记乙二" in prompt
    # opt-in dilemma 候选段同样隐私安全，且不携带任何语义判定词/字段（无 PASS/confidence）
    hit_corpus = tmp_path / "hit_corpus"
    hit_corpus.mkdir()
    (hit_corpus / "secret_alpha.txt").write_text(
        "第1章 一\n甲一。\n第2章 二\n" + "前置内容。" * 400 + "拒绝选择代价执念。\n第3章 三\n甲三。\n",
        encoding="utf-8",
    )
    out2 = tmp_path / "out2"
    run(hit_corpus, out2, sample_chapters=1, dilemma_retrieval=True, dilemma_candidates=2)
    prompt2 = json.loads((out2 / "corpus_author_model_prompt.txt").read_bytes())["prompt"]
    assert "secret_alpha" not in prompt2
    block = prompt2.split("--- dilemma discovery candidates ---", 1)[1]
    candidate_header = "--- dilemma discovery candidate 2 (work-001, middle) ---"
    assert candidate_header in block
    assert "拒绝" in block and "选择" in block
    candidate_text = block.split(candidate_header, 1)[1].split("\n\n---", 1)[0].lstrip("\n")
    assert len(candidate_text) <= 1600
    assert any(pattern.search(candidate_text) for pattern in _DILEMMA_LEXICON.values())
    assert re.search(r"\b(pass|confidence|verdict|score)\b", block, re.IGNORECASE) is None
    assert '"pass"' not in block and '"confidence"' not in block


def test_plain_file_without_chapter_headers_stays_one_corpus_item(tmp_path: Path):
    """无章节标题的 TXT 仍作为单个 corpus item（chapter_title == 全文）。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "随笔.txt").write_text(
        "今天沿着河岸走了很久，风把纸页吹得哗哗作响。\n"
        "没有章节标题的短篇，仍然应该作为单章处理。\n",
        encoding="utf-8",
    )
    size, stats, _, _ = inspect_corpus(corpus, sample_chapters=1)
    assert size["chapter_files"] == 1
    assert size["sampled_chapters"] == 1
    assert stats["chapter_count"] == 1.0

    # Explicitly keep the BOM-less UTF-8 path protected from UTF-16 detection.
    _, _, _, utf8_samples = inspect_corpus(corpus, sample_chapters=1)
    assert utf8_samples[0].text == (
        "今天沿着河岸走了很久，风把纸页吹得哗哗作响。\n"
        "没有章节标题的短篇，仍然应该作为单章处理。"
    )

    for encoding, bom, directory_name in (
        ("utf-16-le", b"\xff\xfe", "utf16-le-corpus"),
        ("utf-16-be", b"\xfe\xff", "utf16-be-corpus"),
    ):
        utf16_corpus = tmp_path / directory_name
        utf16_corpus.mkdir()
        text = f"{directory_name} 无章节标题，仍然作为单章处理。"
        (utf16_corpus / "plain.txt").write_bytes(bom + text.encode(encoding))
        utf16_size, utf16_stats, _, utf16_samples = inspect_corpus(
            utf16_corpus, sample_chapters=1
        )
        assert utf16_size["chapter_files"] == 1
        assert utf16_size["sampled_chapters"] == 1
        assert utf16_stats["chapter_count"] == 1.0
        assert utf16_stats["total_chars"] == float(len(text))
        assert utf16_samples[0].text == text


def test_chapters_directory_keeps_per_file_semantics_without_expansion(tmp_path: Path):
    """chapters/ 目录 = legacy one-file-one-chapter：文件正文即使出现多个
    “第X章”样式字符串，仍计为 1 章，绝不调用 split_by_chapters 展开。"""
    corpus = tmp_path / "corpus"
    (corpus / "chapters").mkdir(parents=True)
    (corpus / "chapters" / "chapter_001.txt").write_text(
        "第1章 开头\n雨落屋檐。\n第2章 结尾\n灯灭人散。\n第3章 尾声\n人去楼空。\n",
        encoding="utf-8",
    )
    size, _, _, _ = inspect_corpus(corpus, sample_chapters=1)
    assert size["chapter_files"] == 1
    assert size["sampled_chapters"] == 1


def test_digest_covers_full_source_text_of_expanded_chapters(tmp_path: Path):
    """digest 覆盖完整原文：修改后段章节文本必须改变 digest，不能只覆盖样本。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    path = corpus / "双章.txt"
    base = "第1章 开端\n山门外的雪还没有停。\n第2章 终局\n炉火映着空椅，来客已在昨夜离去。\n"
    path.write_text(base, encoding="utf-8")
    _, _, digest_before, _ = inspect_corpus(corpus, sample_chapters=2)
    path.write_text(base.replace("来客已在昨夜离去", "来客已在今晨离去"), encoding="utf-8")
    _, _, digest_after, _ = inspect_corpus(corpus, sample_chapters=2)
    assert digest_before != digest_after, "digest 必须反映完整原文变更"


def test_digest_uses_relative_paths_to_disambiguate_same_named_files(tmp_path: Path):
    """digest 用相对路径而非 basename：同名同内容文件从 a/ 移到 b/ 必须改变 digest。"""
    corpus = tmp_path / "corpus"
    (corpus / "a").mkdir(parents=True)
    (corpus / "b").mkdir(parents=True)
    novel_a = corpus / "a" / "novel.txt"
    novel_b = corpus / "b" / "novel.txt"
    content = "第1章 山雨\n山门外雷声滚动。\n"
    novel_a.write_text(content, encoding="utf-8")
    _, _, digest_first, _ = inspect_corpus(corpus, sample_chapters=1)
    # 同名同内容文件挪到另一子目录：仅用 basename 时 digest 会碰撞（路径变更漏检）。
    novel_b.write_text(content, encoding="utf-8")
    novel_a.unlink()
    _, _, digest_moved, _ = inspect_corpus(corpus, sample_chapters=1)
    assert digest_first != digest_moved, "文件相对路径变更必须反映在 digest 中"


def test_legacy_chapters_mode_preserves_digest_and_prompt_format(tmp_path: Path):
    """字节级回归：chapters/ 路径 digest 用 basename（path.name）、prompt 样本头
    保持旧格式 `--- chapter evidence sample N ---`（无 work slot/stage）。"""
    corpus = tmp_path / "corpus"
    (corpus / "chapters").mkdir(parents=True)
    (corpus / "chapters" / "chapter_001.txt").write_text("人物突然转身。", encoding="utf-8")
    (corpus / "chapters" / "chapter_002.txt").write_text("“他说道：继续。”", encoding="utf-8")
    (corpus / "chapters" / "chapter_003.txt").write_text("夜色中，她终于做了决定。", encoding="utf-8")
    output = tmp_path / "out"
    waiting = run(corpus, output, sample_chapters=3)
    assert waiting["status"] == "waiting"
    # 1) digest 字节级等于测试内 legacy reference（path.name + 原文，逐文件排序）
    expected = hashlib.sha256()
    for path in sorted((corpus / "chapters").glob("*.txt")):
        expected.update(path.name.encode("utf-8"))
        expected.update(path.read_bytes())
    assert waiting["source_digest"] == expected.hexdigest()
    # 2) prompt 样本头字节级保持旧格式
    prompt_payload = json.loads((output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8"))
    prompt = prompt_payload["prompt"]
    assert "--- chapter evidence sample 1 ---" in prompt
    assert "--- chapter evidence sample 2 ---" in prompt
    assert "--- chapter evidence sample 3 ---" in prompt
    assert "(work-" not in prompt
    # 3) opt-in 零成本字节锁：禁用模式（含不同 candidate 数）下 prompt 文件 raw bytes
    #    与 run 返回 dict 逐字节不变；启用时才追加（默认 prompt 是 opt-in 前缀）。
    prompt_bytes = (output / "corpus_author_model_prompt.txt").read_bytes()
    rerun = run(corpus, output, sample_chapters=3, dilemma_retrieval=False, dilemma_candidates=7)
    assert rerun == waiting, "禁用模式 run 返回 dict 必须逐字节一致"
    assert (output / "corpus_author_model_prompt.txt").read_bytes() == prompt_bytes
    out_on = tmp_path / "out-on"
    run(corpus, out_on, sample_chapters=3, dilemma_retrieval=True, dilemma_candidates=2)
    on_prompt = json.loads((out_on / "corpus_author_model_prompt.txt").read_bytes())["prompt"]
    assert on_prompt.startswith(prompt), "opt-in 只追加到未改动的默认 prompt"


def test_sampled_chapters_is_actual_not_padded_when_quota_exceeds_chapter_count(tmp_path: Path):
    """预算超过总章数时 actual sampled < 请求值：诚实报告，不复制样本凑数。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # 作品 A 仅 1 章；作品 B 3 章；总章数 4，请求 5 → 实际 4
    (corpus / "one_chapter_book.txt").write_text(
        "第1章 独章\n独章标记。\n",
        encoding="utf-8",
    )
    (corpus / "three_chapter_book.txt").write_text(
        "第1章 三一\n三章标记1。\n第2章 三二\n三章标记2。\n第3章 三三\n三章标记3。\n",
        encoding="utf-8",
    )
    size, _, _, _ = inspect_corpus(corpus, sample_chapters=5)
    assert size["chapter_files"] == 4
    assert size["sampled_chapters"] == 4, "实际抽样数 4（总章数上限），不能复制样本凑到 5"
    # dilemma 检索同样诚实：score>0 未选章节不足时 retrieved < requested，
    # 完全无命中时 retrieved=0，段内 metadata 如实报告 shortfall。
    corpus2 = tmp_path / "corpus2"
    (corpus2 / "chapters").mkdir(parents=True)
    (corpus2 / "chapters" / "chapter_001.txt").write_text("人物突然转身。", encoding="utf-8")
    (corpus2 / "chapters" / "chapter_002.txt").write_text("夜色中，她终于走了。", encoding="utf-8")
    assert retrieve_dilemma_candidates(corpus2, selected={0}, requested=3) == ([], 3)
    out2 = tmp_path / "out2"
    run(corpus2, out2, sample_chapters=1, dilemma_retrieval=True, dilemma_candidates=3)
    prompt2 = json.loads((out2 / "corpus_author_model_prompt.txt").read_bytes())["prompt"]
    assert 'Candidate metadata: {"requested": 3, "retrieved": 0, "shortfall": 3}' in prompt2
    assert "(no candidates available)" in prompt2


def test_bounded_work_quotas_redistributes_unused_quota():
    """[1, 100, 100] / budget=36：初始公平 quota [12,12,12] 被 cap 后，
    未用额度确定性轮转重分配给有容量的作品 → 总和 36、首作 1、其余分完。"""
    quotas = _bounded_work_quotas([1, 100, 100], 36)
    assert sum(quotas) == 36
    assert quotas[0] == 1, "1 章作品 cap 后只能取 1"
    assert sum(quotas[1:]) == 35
    assert quotas[1] > 12 and quotas[2] > 12, "未用额度必须重分配给有容量作品"
    assert all(quota <= count for quota, count in zip(quotas, [1, 100, 100]))


def test_bounded_work_quotas_legacy_all_ones_equals_old_global():
    """legacy 全 1（chapters/ 模式）仍等价旧全局均匀：budget 超过作品数时
    每作 1 个（= 总章数），预算不足时等于旧 _sample_indexes 选作。"""
    assert _bounded_work_quotas([1] * 10, 20) == [1] * 10
    assert _bounded_work_quotas([1] * 10, 5) == [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]
    assert sum(_bounded_work_quotas([1] * 10, 5)) == 5
