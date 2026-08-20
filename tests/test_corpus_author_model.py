from pathlib import Path
import hashlib
import json

import pytest

from src.object_state.corpusauthormodel import Author, SelectionPattern
from src.workflow_action.corpus_author_model import (
    _bounded_work_quotas,
    _stratified_work_quotas,
    extract_authors,
    inspect_corpus,
    run,
)


def test_author_requires_chapter_evidence():
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="neutral pattern",
            confidence=0.5,
            chapter_evidence=[],
        )


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
    # 第一本 quota 2：`_sample_indexes(3, 2)` = 第 1、3 章 → 首末阶段证据
    assert "晨雾" in prompt, "第一本第 1 章必须被抽样"
    assert "灯台守夜人" in prompt, "第一本第 3 章必须被抽样"
    # 第二本 quota 1：代表样本 = 第 1 章
    assert "站台" in prompt, "第二本必须有样本"
    assert "旧剧场" not in prompt, "第二本 quota 1 只抽第 1 章"
    # 中性 work slot + 阶段 + 全局编号（隐私安全来源分组）
    assert "chapter evidence sample 1 (work-001, early)" in prompt
    assert "chapter evidence sample 3 (work-001, late)" in prompt
    assert "chapter evidence sample 4 (work-002, early)" in prompt
    assert "alpha_book" not in prompt
    assert "beta_book" not in prompt


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
    # 长书 quota 2：首章与末章都有阶段证据
    assert "长书独有标记1" in prompt, "长书第 1 章必须被抽样"
    assert "长书独有标记20" in prompt, "长书第 20 章必须被抽样"
    # 短书 quota 2：两章全被覆盖（短书全部章节都有代表）
    assert "短书独有标记1" in prompt, "短书第 1 章必须被抽样"
    assert "短书独有标记2" in prompt, "短书第 2 章必须被抽样"
    # 中性 work slot + 阶段 + 全局编号，且无源文件名
    assert "chapter evidence sample 1 (work-001, early)" in prompt
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
