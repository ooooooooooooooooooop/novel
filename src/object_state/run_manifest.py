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
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
