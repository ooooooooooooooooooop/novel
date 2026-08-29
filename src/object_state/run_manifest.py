"""RunManifest — 事务式章节提交的版本化运行记录.

Q1 Phase 2（事务式提交与版本化运行）核心模型。一次「续写/创作一章」从
staged（响应已物化）→ draft（正文落盘）→ reviewed（Review PASS）→
committed（正文+状态+Frame 原子提交）或 rejected（阻断/人工拒绝）。

流 v3 契约：
- run_manifest.json 是提交记录（commit record），正文/状态/Frame 全部先落盘，
  manifest 最后原子写入——崩溃后重启只识别完整提交。
- artifacts 记录本次提交所有产物的 sha256（相对 novel 工作区路径）；
  recover() 逐项校验，任一缺失/不匹配 → 不识别为已提交，绝不产生
  「正文已存在但状态未更新」或相反的半提交。
- 状态必须带正文证据（draft_hash/facts_package_hash）与状态前后哈希
  （state_before_hash/state_after_hash），无证据不写入（Q1 原则）。

隐私纪律：本文件存于小说工作区 output/<mode>/ 下（已 gitignore），
不含小说名/笔名等可发布信息；run_id 由 mode+章节号派生，可跨机复核。
"""

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunStatus = Literal["staged", "draft", "reviewed", "committed", "rejected"]

# 五态合法迁移表：staged → draft → reviewed → committed / rejected
# rejected 是终态；committed 是终态。允许幂等重设同态（重跑同一章节尝试）。
_RUN_STATUS_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    "staged": {"staged", "draft"},
    "draft": {"draft", "reviewed"},
    "reviewed": {"reviewed", "committed", "rejected"},
    "committed": {"committed"},
    "rejected": {"rejected"},
}

# 相对 novel 工作区（output_dir.parent.parent）的产物路径 → sha256
ArtifactMap = dict[str, str]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    """计算文件 sha256；文件不存在返回 None 语义由调用方处理（这里抛错）。"""
    return sha256_bytes(path.read_bytes())


def hash_file_if_exists(path: Path) -> str | None:
    return sha256_file(path) if path.exists() else None


class RunManifest(BaseModel):
    """一次运行的提交/状态记录.

    kind == "run" 的 committed 记录是提交证据；kind == "seed" 是 v2→v3 迁移
    建立的基线（记录 v2 链的末尾章节号，让 v3 从正确编号续写且不误报孤儿）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    kind: Literal["run", "seed"] = "run"
    run_id: str = Field(description="运行标识（mode + 章节号派生，重跑同章复用）")
    flow_version: Literal["2", "3"] = "3"
    mode: Literal["compose", "extend", "migrate"] = Field(
        description="产生该运行的流"
    )
    status: RunStatus = Field(description="五态之一")

    # 章节标识
    chapter_ref: str | None = Field(
        default=None, description="如 chapter_1206"
    )
    chapter_number: int | None = Field(
        default=None, description="章节编号（无前导零）"
    )
    prev_chapter_ref: str | None = Field(
        default=None, description="前章引用（续写链头）"
    )

    # 输入/事实/状态哈希（无证据不写入）
    source_text_hash: str | None = Field(
        default=None, description="原文/WorkSpec 哈希（compose=workspec，extend=input）"
    )
    campaign_identity_hash: str | None = Field(
        default=None, description="A1 campaign_identity.json 哈希（直接自动入口身份锁）"
    )
    prev_chapter_hash: str | None = Field(
        default=None, description="前章正文哈希"
    )
    draft_hash: str | None = Field(
        default=None, description="本章正文草稿哈希（sha256(prose_draft.txt)）"
    )
    facts_package_hash: str | None = Field(
        default=None, description="ProseEvidencePackage 哈希（事实包，Phase 3/4 对接）"
    )
    state_before_hash: str | None = Field(
        default=None, description="提交前状态包哈希（旧链头）"
    )
    state_after_hash: str | None = Field(
        default=None, description="提交后状态包哈希（新链头）"
    )
    frame_hash: str | None = Field(
        default=None, description="Frame 光标状态哈希（提交后）"
    )

    # 核心产物的显式路径绑定（相对 novel 工作区，字段哈希必须与 artifacts 交叉一致）
    chapter_artifact: str | None = None
    draft_artifact: str | None = None
    state_artifact: str | None = None
    frame_artifact: str | None = None
    provenance_artifact: str | None = None
    reader_gate_artifact: str | None = None
    serial_reader_artifact: str | None = None
    blind_final_audit_artifact: str | None = None
    campaign_identity_artifact: str | None = None

    # 提交记录：所有产物文件 → sha256（相对 novel 工作区路径）
    artifacts: ArtifactMap = Field(
        default_factory=dict,
        description="本次提交全部产物的 sha256（recover 逐项校验用）",
    )

    review_route: str | None = Field(
        default=None, description="Review 路由（pass/rewrite/...，非空说明已过 Review）"
    )
    notes: list[str] = Field(default_factory=list, description="人工/系统备注")

    created_at_utc: str | None = Field(
        default=None, description="运行创建时刻（UTC ISO-8601）"
    )
    committed_at_utc: str | None = Field(
        default=None, description="提交时刻（UTC ISO-8601，committed 才非空）"
    )

    # 迁移种子专用
    seeded: bool = False
    seeded_from_flow: str | None = Field(
        default=None, description="种子来源流（migrate 种子为 '2'）"
    )

    @model_validator(mode="after")
    def _committed_run_has_complete_evidence(self) -> "RunManifest":
        if self.kind != "run" or self.status != "committed":
            return self
        required = {
            "chapter_ref": self.chapter_ref,
            "chapter_number": self.chapter_number,
            "draft_hash": self.draft_hash,
            "facts_package_hash": self.facts_package_hash,
            "state_before_hash": self.state_before_hash,
            "state_after_hash": self.state_after_hash,
            "frame_hash": self.frame_hash,
            "review_route": self.review_route,
            "committed_at_utc": self.committed_at_utc,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing or not self.artifacts:
            raise ValueError(
                "committed run requires complete evidence: "
                + ", ".join(missing + (["artifacts"] if not self.artifacts else []))
            )
        for path, digest in self.artifacts.items():
            posix = PurePosixPath(path)
            if (
                not path
                or posix.is_absolute()
                or ".." in posix.parts
                or "\\" in path
            ):
                raise ValueError(f"unsafe artifact path: {path!r}")
            if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                raise ValueError(f"invalid artifact sha256 for {path!r}")
        bound = {
            "chapter_artifact": (self.chapter_artifact, self.draft_hash),
            "draft_artifact": (self.draft_artifact, self.draft_hash),
            "state_artifact": (self.state_artifact, self.state_after_hash),
            "frame_artifact": (self.frame_artifact, self.frame_hash),
        }
        for name, (path, expected_hash) in bound.items():
            if not path or self.artifacts.get(path) != expected_hash:
                raise ValueError(f"{name} must bind its manifest hash in artifacts")
        expected_chapter = f"chapters/chapter_{self.chapter_number}.txt"
        if self.chapter_artifact != expected_chapter:
            raise ValueError("chapter_artifact must bind the committed chapter number")
        if not self.draft_artifact.endswith(
            f"/prose_history/draft_chapter_{self.chapter_number}.txt"
        ):
            raise ValueError("draft_artifact must bind the committed chapter draft")
        for name, path in (
            ("state_artifact", self.state_artifact),
            ("frame_artifact", self.frame_artifact),
        ):
            if not path.startswith("output/"):
                raise ValueError(f"{name} must stay under output/")
        for name in (
            "provenance_artifact",
            "reader_gate_artifact",
            "serial_reader_artifact",
            "blind_final_audit_artifact",
        ):
            path = getattr(self, name)
            if path is not None and self.artifacts.get(path) is None:
                raise ValueError(f"{name} must be present in artifacts")
        if self.chapter_number and self.chapter_number > 1:
            if not self.prev_chapter_ref or not self.prev_chapter_hash:
                raise ValueError(
                    "committed chapter after chapter_1 requires prev chapter evidence"
                )
        if self.campaign_identity_hash is not None:
            if (
                not self.campaign_identity_artifact
                or self.artifacts.get(self.campaign_identity_artifact)
                != self.campaign_identity_hash
            ):
                raise ValueError(
                    "campaign identity artifact must bind campaign_identity_hash"
                )
            if (
                not self.provenance_artifact
                or not self.reader_gate_artifact
                or not self.blind_final_audit_artifact
            ):
                raise ValueError(
                    "A1 committed run requires provenance/reader/blind-final artifacts"
                )
            if self.chapter_number and self.chapter_number >= 3 and not self.serial_reader_artifact:
                raise ValueError(
                    "A1 chapter_3+ committed run requires serial reader artifact"
                )
        return self

    def transition_allowed(self, target: RunStatus) -> bool:
        """校验 status → target 是否在合法迁移表内（幂等重设同态允许）。"""
        return target in _RUN_STATUS_TRANSITIONS.get(self.status, set())

    def next_chapter_number(self) -> int | None:
        """链头章号：committed 的 run 或 seed 提供下一个续写编号."""
        if self.status != "committed":
            return None
        if self.chapter_number is None:
            return 1
        return self.chapter_number + 1


def read_run_manifest(output_dir: Path) -> RunManifest | None:
    """读取 output/<mode>/run_manifest.json；不存在或非法返回 None（不抛错）。"""
    path = output_dir / "run_manifest.json"
    if not path.exists():
        return None
    try:
        data = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return RunManifest.model_validate_json(data)
    except Exception:
        return None
