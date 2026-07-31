"""Run identity guards for staged workflow output directories."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

CONTENT_HASH_LENGTH = 32
LOWER_HEX_DIGITS = set("0123456789abcdef")
STAGED_PROMPT_SUFFIX = "_prompt.txt"
STAGED_RESPONSE_SUFFIX = "_response.txt"
STAGED_SLOT_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "_-"
)


@dataclass(frozen=True)
class FileContentEvidence:
    """Content identity metadata produced from one byte snapshot."""

    content_hash: str
    byte_count: int

    def __post_init__(self) -> None:
        content_hash = validate_content_hash(
            self.content_hash,
            "file content evidence content_hash",
        )
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool):
            raise ValueError(
                f"invalid file content evidence byte_count: {self.byte_count}"
            )
        if self.byte_count < 0:
            raise ValueError(
                f"invalid file content evidence byte_count: {self.byte_count}"
            )
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "byte_count", self.byte_count)


def content_evidence_from_bytes(data: bytes) -> FileContentEvidence:
    return FileContentEvidence(
        content_hash=hashlib.md5(data).hexdigest(),
        byte_count=len(data),
    )


def file_content_evidence(path: Path) -> FileContentEvidence:
    return content_evidence_from_bytes(Path(path).read_bytes())


def file_content_hash(path: Path) -> str:
    return file_content_evidence(path).content_hash



def validate_content_hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != CONTENT_HASH_LENGTH
        or any(char not in LOWER_HEX_DIGITS for char in value)
    ):
        raise ValueError(f"invalid {label}: {value}")
    return value


def validate_staged_slot_id(value: object, label: str = "slot_id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid {label}: {value}")
    if value != value.strip():
        raise ValueError(f"invalid {label}: {value}")
    if Path(value).name != value:
        raise ValueError(f"invalid {label}: {value}")
    if value.endswith(STAGED_PROMPT_SUFFIX) or value.endswith(STAGED_RESPONSE_SUFFIX):
        raise ValueError(f"invalid {label}: {value}")
    if any(char not in STAGED_SLOT_CHARS for char in value):
        raise ValueError(f"invalid {label}: {value}")
    return value


def _staged_prompt_slot(prompt_path: Path) -> tuple[Path, str]:
    prompt_path = Path(prompt_path)
    if prompt_path.name.endswith(STAGED_PROMPT_SUFFIX):
        slot_id = validate_staged_slot_id(
            prompt_path.name.removesuffix(STAGED_PROMPT_SUFFIX),
            "prompt slot id",
        )
        return prompt_path, slot_id
    raise ValueError(f"prompt file must end with _prompt.txt: {prompt_path}")


def expected_staged_response_path(prompt_path: Path) -> Path:
    prompt_path, slot_id = _staged_prompt_slot(prompt_path)
    return prompt_path.with_name(f"{slot_id}_response.txt")


def staged_slot_id(prompt_path: Path) -> str:
    _prompt_path, slot_id = _staged_prompt_slot(prompt_path)
    return slot_id


def model_content_hash(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _has_existing_artifacts(output_dir: Path, hash_path: Path) -> bool:
    if not output_dir.exists():
        return False
    hash_path = hash_path.resolve()
    for path in output_dir.rglob("*"):
        if path.is_file() and path.resolve() != hash_path:
            return True
    return False


def validate_run_hash(
    *,
    hash_path: Path,
    current_hash: str,
    output_dir: Path,
    label: str,
    write_hash: bool = True,
) -> list[str]:
    if hash_path.exists():
        saved_hash = hash_path.read_text(encoding="utf-8").strip()
        if saved_hash != current_hash:
            return [
                f"Error: {label} hash mismatch.",
                f"Expected hash from previous run: {saved_hash}",
                f"Current {label} hash: {current_hash}",
                f"Output dir preserved without deleting response files: {output_dir}",
            ]
        return []

    if _has_existing_artifacts(output_dir, hash_path):
        return [
            f"Error: missing {label} hash for non-empty output dir.",
            f"Output dir preserved without deleting response files: {output_dir}",
        ]

    if write_hash:
        hash_path.write_text(current_hash, encoding="utf-8")
    return []
