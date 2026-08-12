"""ReaderResponses 测试（design §10 / T7.3）.

`responses/<reader_id>.json` 逐份留存、禁止覆盖、元数据可追溯.
"""

import json

import pytest

from src.object_state.readerresponse import ReaderResponseRecord
from src.workflow_action.reader_responses import (
    ReaderResponseAlreadyExists,
    load_reader_response,
    responses_dir,
    store_reader_response,
)


def _record(reader_id: str = "reader-01", **updates) -> ReaderResponseRecord:
    payload = {
        "reader_id": reader_id,
        "prompt_hash": "p" * 64,
        "model": "model-a",
        "model_version": "1.0",
        "sampling": "temperature=0.0",
        "run_id": "run-a",
        "prose_package_hash": "b" * 64,
        "response": '{"preferred": "A"}',
    }
    payload.update(updates)
    return ReaderResponseRecord.model_validate(payload)


def test_store_writes_responses_reader_id_json(tmp_path):
    path = store_reader_response(tmp_path, _record(reader_id="reader-01"))
    assert path.name == "reader-01.json"
    assert path.parent.name == "responses"
    assert path.is_file()


def test_store_refuses_overwrite_same_reader_id(tmp_path):
    store_reader_response(tmp_path, _record(reader_id="reader-01"))
    with pytest.raises(ReaderResponseAlreadyExists):
        store_reader_response(tmp_path, _record(reader_id="reader-01"))
    # force 才允许显式覆盖
    store_reader_response(tmp_path, _record(reader_id="reader-01", response="v2"), force=True)
    assert load_reader_response(tmp_path, "reader-01").response == "v2"


def test_store_allows_distinct_reader_ids(tmp_path):
    store_reader_response(tmp_path, _record(reader_id="reader-01"))
    store_reader_response(tmp_path, _record(reader_id="reader-02"))
    paths = sorted(p.name for p in responses_dir(tmp_path).iterdir())
    assert paths == ["reader-01.json", "reader-02.json"]


def test_load_roundtrip_preserves_metadata(tmp_path):
    record = _record(reader_id="reader-01", response='{"preferred": "B"}')
    store_reader_response(tmp_path, record)
    loaded = load_reader_response(tmp_path, "reader-01")
    assert loaded is not None
    assert loaded.model == "model-a"
    assert loaded.prompt_hash == "p" * 64
    assert loaded.prose_package_hash == "b" * 64
    assert loaded.response == '{"preferred": "B"}'


def test_load_missing_returns_none(tmp_path):
    assert load_reader_response(tmp_path, "nope") is None


def test_reader_response_rejects_blank_identity_fields():
    with pytest.raises(Exception):
        ReaderResponseRecord.model_validate(
            {
                "reader_id": "",
                "prompt_hash": "p" * 64,
                "model": "model-a",
                "run_id": "run-a",
                "prose_package_hash": "b" * 64,
                "response": "x",
            }
        )


def test_stored_file_is_json_without_privacy_leak(tmp_path):
    store_reader_response(tmp_path, _record(reader_id="reader-01"))
    data = json.loads(
        (responses_dir(tmp_path) / "reader-01.json").read_text(encoding="utf-8")
    )
    # 元数据 + 响应本身，不含正文/小说名
    assert set(data) >= {"reader_id", "prompt_hash", "model", "run_id", "response"}
    assert "chapters" not in data
