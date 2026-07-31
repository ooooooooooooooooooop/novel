"""Tests for SerializationPackage runtime metadata."""

import json

import pytest
from pydantic import ValidationError

from src.boundary_control.serialization import (
    SerializationBoundaryUnit,
    SerializationPackage,
)
from src.object_state import WorkSpec


def test_package_metadata_default_empty():
    assert SerializationPackage().metadata == {}


def test_package_metadata_roundtrip(tmp_path):
    path = tmp_path / "package.json"
    package = SerializationPackage(metadata={"outline_used": True, "outline_arcs_count": 2})

    serializer = SerializationBoundaryUnit()
    serializer.save(package, path)
    loaded = serializer.load(path)

    assert loaded.metadata == {"outline_used": True, "outline_arcs_count": 2}


def test_package_metadata_not_in_check_separation():
    package = SerializationPackage(
        metadata={
            "WorkSpec": "metadata should not be treated as a layer bucket",
            "ReviewIssue": "metadata should not violate separation",
        }
    )

    assert SerializationBoundaryUnit().check_separation(package) == []


def test_deserialize_ignores_non_object_confidence_data():
    package = SerializationPackage(confidence={"gaps": ["代理人名单正文未知"]})

    assert SerializationBoundaryUnit().deserialize_package(package) == []


def test_load_rejects_unknown_top_level_package_fields(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(
        json.dumps({"stable_memroy": {"WorkSpec": []}}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stable_memroy"):
        SerializationBoundaryUnit().load(path)


def test_serialization_package_assignment_revalidates_json_container_shapes():
    package = SerializationPackage()

    with pytest.raises(ValidationError, match="working_set"):
        package.working_set = ["not", "an", "object"]
    with pytest.raises(ValidationError, match="metadata"):
        package.metadata = {1: "bad"}
    with pytest.raises(ValidationError, match="confidence"):
        package.confidence = {1: "bad"}


def test_serialization_package_model_copy_update_revalidates_payload():
    package = SerializationPackage(metadata={"outline_used": True})

    copied = package.model_copy(update={"metadata": {"outline_used": False}})

    assert copied.metadata == {"outline_used": False}
    assert package.metadata == {"outline_used": True}
    with pytest.raises(ValidationError, match="working_set"):
        package.model_copy(update={"working_set": ["not", "an", "object"]})
    with pytest.raises(ValidationError, match="metadata"):
        package.model_copy(update={"metadata": {1: "bad"}})


def test_serialization_package_runtime_containers_are_shallow_read_only():
    package = SerializationBoundaryUnit().build_package(
        # WorkSpec is enough to populate a stable-memory bucket and object entry.
        WorkSpec(
            genre="test",
            audience="test",
            theme="test",
            tone="test",
            pacing="test",
        )
    )
    metadata_package = SerializationPackage(metadata={"outline_used": True})

    with pytest.raises(TypeError):
        package.stable_memory["WorkSpecExtra"] = []
    with pytest.raises(AttributeError):
        package.stable_memory["WorkSpec"].append({})
    with pytest.raises(TypeError):
        package.stable_memory["WorkSpec"][0]["genre"] = "mutated"
    with pytest.raises(TypeError):
        metadata_package.metadata["outline_used"] = False

    dumped = package.model_dump()
    assert isinstance(dumped["stable_memory"], dict)
    assert isinstance(dumped["stable_memory"]["WorkSpec"], list)
    assert isinstance(dumped["stable_memory"]["WorkSpec"][0], dict)


def test_serialization_package_model_copy_deep_rebuilds_read_only_payload():
    package = SerializationPackage(
        stable_memory={
            "WorkSpec": [
                {
                    "genre": "test",
                    "audience": "test",
                    "theme": "test",
                    "tone": "test",
                    "pacing": "test",
                }
            ]
        },
        metadata={"outline_used": True},
    )

    deep_copied = package.model_copy(deep=True)
    deep_updated = package.model_copy(
        update={"metadata": {"outline_used": False}},
        deep=True,
    )

    assert deep_copied.model_dump() == package.model_dump()
    assert deep_updated.metadata == {"outline_used": False}
    with pytest.raises(TypeError):
        deep_copied.stable_memory["Other"] = []
    with pytest.raises(TypeError):
        deep_updated.metadata["outline_used"] = True
