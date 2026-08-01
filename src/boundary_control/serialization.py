"""SerializationBoundaryUnit — 序列化边界控制."""

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
)

from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    ReviewReminder,
    WorkSpec,
    WorldModel,
)


SerializedLayer = Mapping[str, tuple[Mapping[str, object], ...]]
PackageMetadata = Mapping[str, object]

SERIALIZED_LAYER_TYPES = {
    "stable_memory": {
        "WorkSpec",
        "WorldModel",
        "CharacterModel",
        "FactLedger",
        "FactEntry",
        "ForeshadowEntry",
        "ForeshadowGraph",
    },
    "working_set": {
        "NarrativeState",
        "PlotUnit",
    },
    "repair_control": {
        "ReviewIssue",
        "ReviewReminder",
    },
}
KNOWN_SERIALIZED_TYPES = set().union(*SERIALIZED_LAYER_TYPES.values())


class SerializationPackage(BaseModel):
    """四层序列化包."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    stable_memory: SerializedLayer = Field(default_factory=dict)
    working_set: SerializedLayer = Field(default_factory=dict)
    repair_control: SerializedLayer = Field(default_factory=dict)
    confidence: PackageMetadata = Field(default_factory=dict)
    metadata: PackageMetadata = Field(default_factory=dict)

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> "SerializationPackage":
        if update is None:
            if deep:
                return type(self).model_validate(self.model_dump())
            return super().model_copy(deep=deep)
        payload = self.model_dump()
        payload.update(update)
        copied = type(self).model_validate(payload)
        if deep:
            return type(self).model_validate(copied.model_dump())
        return copied

    @field_validator("stable_memory", "working_set", "repair_control")
    @classmethod
    def _serialized_layers_are_read_only(
        cls, value: SerializedLayer
    ) -> SerializedLayer:
        frozen_layer = {}
        for type_name, items in value.items():
            frozen_layer[type_name] = tuple(
                MappingProxyType(dict(item)) for item in items
            )
        return MappingProxyType(frozen_layer)

    @field_validator("confidence", "metadata")
    @classmethod
    def _metadata_is_read_only(cls, value: PackageMetadata) -> PackageMetadata:
        return MappingProxyType(dict(value))

    @field_serializer("stable_memory", "working_set", "repair_control")
    def _serialized_layers_dump_as_json_objects(
        self, value: SerializedLayer
    ) -> dict[str, list[dict[str, object]]]:
        return {
            type_name: [dict(item) for item in items]
            for type_name, items in value.items()
        }

    @field_serializer("confidence", "metadata")
    def _metadata_dump_as_json_objects(
        self, value: PackageMetadata
    ) -> dict[str, object]:
        return dict(value)


class SerializationBoundaryUnit:
    """序列化边界单元.

    职责: 将对象状态映射到正确的序列化层.
    不裁决事实, 不决定角色结论, 不分类审查问题.
    """

    # 对象 → 默认序列化层映射
    _LAYER_MAP: dict[type, str] = {
        WorkSpec: "stable_memory",
        WorldModel: "stable_memory",
        CharacterModel: "stable_memory",
        FactLedger: "stable_memory",
        ForeshadowEntry: "stable_memory",
        ForeshadowGraph: "stable_memory",
        NarrativeState: "working_set",
        PlotUnit: "working_set",
        ReviewIssue: "repair_control",
        ReviewReminder: "repair_control",
    }

    def serialize_object(self, obj: BaseModel) -> tuple[str, dict]:
        """将单个对象序列化到 (层名, 字典).

        Returns:
            (layer_name, serialized_dict)
        """
        layer = self._LAYER_MAP.get(type(obj))
        if layer is None:
            raise ValueError(f"Unknown serializable object type: {type(obj).__name__}")
        return layer, obj.model_dump(mode="json")

    def build_package(self, *objects: BaseModel) -> SerializationPackage:
        """将多个对象打包到正确的层."""
        package_data = SerializationPackage().model_dump()
        for obj in objects:
            layer, data = self.serialize_object(obj)
            # 按对象类型分桶
            bucket = package_data[layer]
            type_key = type(obj).__name__
            if type_key not in bucket:
                bucket[type_key] = []
            bucket[type_key].append(data)
        return SerializationPackage.model_validate(package_data)

    def save(self, package: SerializationPackage, path: Path) -> None:
        """保存到 JSON 文件."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(package.model_dump(), f, ensure_ascii=False, indent=2)

    def load(self, path: Path) -> SerializationPackage:
        """从 JSON 文件加载."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        try:
            return SerializationPackage(**data)
        except ValidationError as exc:
            raise ValueError(f"Invalid serialization package: {exc}") from exc

    def deserialize_package(self, package: SerializationPackage) -> list:
        """将 SerializationPackage 反序列化为 Pydantic 对象列表."""
        objects = []
        type_map = {
            "WorkSpec": WorkSpec,
            "WorldModel": WorldModel,
            "CharacterModel": CharacterModel,
            "NarrativeState": NarrativeState,
            "FactLedger": FactLedger,
            "FactEntry": FactEntry,
            "ForeshadowGraph": ForeshadowGraph,
            "ForeshadowEntry": ForeshadowEntry,
            "PlotUnit": PlotUnit,
            "ReviewIssue": ReviewIssue,
            "ReviewReminder": ReviewReminder,
        }

        for layer in ["stable_memory", "working_set", "repair_control"]:
            bucket = getattr(package, layer)
            for type_name, items in bucket.items():
                cls = type_map.get(type_name)
                if not cls:
                    raise ValueError(f"Unknown serialized object type: {type_name}")
                for item in items:
                    if not isinstance(item, Mapping):
                        raise ValueError(
                            f"Serialized {type_name} item must be an object"
                        )
                    # 只要求必填字段存在; 可选字段(如 FactEntry.validity_interval)
                    # 缺省时由模型默认值补齐, 保证旧 state 可反序列化。
                    missing_fields = [
                        field_name
                        for field_name, field_def in cls.model_fields.items()
                        if field_def.is_required() and field_name not in item
                    ]
                    if missing_fields:
                        raise ValueError(
                            f"Serialized {type_name} missing serialized field(s): "
                            f"{', '.join(missing_fields)}"
                        )
                    try:
                        objects.append(cls(**dict(item)))
                    except Exception as e:
                        raise ValueError(f"Failed to deserialize {type_name}: {e}") from e

        return objects

    def check_separation(self, package: SerializationPackage) -> list[str]:
        """检查层分离是否被破坏.

        Returns:
            违规描述列表. 空列表表示通过.
        """
        violations = []
        for layer_name, allowed_types in SERIALIZED_LAYER_TYPES.items():
            bucket = getattr(package, layer_name)
            for type_name in bucket:
                if type_name not in KNOWN_SERIALIZED_TYPES:
                    violations.append(f"{layer_name} contains unknown type {type_name}")
                elif type_name not in allowed_types:
                    violations.append(f"{layer_name} contains {type_name}")
        return violations
