"""ChapterCommitBoundary — 章节提交的事务边界（Q1 Phase 2）.

流 v2 的隐患（Phase 2 要修掉的）：compose/extend 按顺序写 chapter 文件 →
archive → provenance → advance Frame → save state；任一点崩溃都会留下
「正文已存在但状态未更新」或相反的半提交，且没有记录可判断哪些产物是完整的。

流 v3（本模块）的提交协议：
1. 所有产物（正文/归档/provenance/Frame/状态包）先在内存里备好，逐一落盘；
2. run_manifest.json 是**提交记录**，最后以原子写（tmp + os.replace）落盘，
   记录全部产物的相对路径与 sha256；
3. 崩溃后重启 `recover()`：manifest 存在 且 逐项哈希校验通过 → 识别为完整提交；
   否则一律**不识别为已提交**——绝不把孤立的 chapter 文件或孤立的 state 文件
   当成合法链头，杜绝半提交。

五态生命周期：staged（响应已物化，隐式）→ draft → reviewed → committed / rejected。
`set_run_status` 幂等推进状态机（见 run_manifest.RunStatus 迁移表）。

`failpoint` 仅供测试注入崩溃（在指定写步骤前抛错），生产路径不启用。
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.run_manifest import (
    RunManifest,
    RunStatus,
    hash_file_if_exists,
    read_run_manifest,
    sha256_file,
    sha256_text,
)

RUN_MANIFEST_FILENAME = "run_manifest.json"
RUN_HISTORY_DIR = "run_history"
_TMP_SUFFIX = ".tmp"

# failpoint 步骤名（测试注入崩溃的写点）
FAILPOINT_STEPS = (
    "chapter", "archive", "provenance", "frames", "state", "orchestration", "manifest",
    "manifest.replace",
)

Mode = Literal["compose", "extend"]


class UnmanagedArtifactError(ValueError):
    """目标章节文件已存在但未被当前提交链覆盖（孤儿产物），拒绝覆盖。"""


class CommitResult(BaseModel):
    """一次提交的结果。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    run_manifest: RunManifest | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class RecoveryReport(BaseModel):
    """崩溃恢复判定：重启后是否应把产物识别为完整提交。"""

    model_config = ConfigDict(extra="forbid")

    recognized: bool
    reason: str = Field(
        description="committed | no_manifest | status_<s> | artifact_missing | artifact_mismatch | orphan_artifact"
    )
    manifest: RunManifest | None = None
    missing: list[str] = Field(default_factory=list, description="缺失产物（相对 novel 路径）")
    mismatched: list[dict] = Field(
        default_factory=list, description="[{\"path\", \"expected\", \"actual\"}] 哈希不符产物"
    )
    orphans: list[str] = Field(default_factory=list, description="未被提交链覆盖的孤立 chapter 文件")
    stale_tmp: list[str] = Field(default_factory=list, description="遗留的 manifest 临时文件")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def derive_run_id(mode: str, chapter_number: int) -> str:
    """运行标识：mode + 章节号派生——重跑同一章尝试复用同一 manifest。"""
    return f"{mode}-{chapter_number}"


def read_flow_version(output_dir: Path) -> str:
    path = output_dir / ".flow_version"
    if not path.exists():
        return "2"
    value = path.read_text(encoding="utf-8").strip()
    return value if value in ("2", "3") else "2"


def seed_v2_baseline(
    output_dir: Path,
    *,
    run_id: str,
    mode: Mode,
    chapter_number: int | None,
    notes: list[str] | None = None,
) -> RunManifest:
    """flow v2 → v3 迁移种子：把 v2 链末尾章节号固化为合法基线.

    调用方负责先把 .flow_version 置为 3；本函数只原子落盘 seed manifest。
    seed 的 artifacts 为空（旧产物不属于 v3 提交），recover() 对 seed 校验
    恒通过 → 识别为合法基线，续写从 chapter_number + 1 开始，且不误报孤儿。
    旧产物只读不写（--preserve-old 语义由 CLI 层保证，本函数不删除任何文件）。
    """
    seed = RunManifest(
        kind="seed",
        run_id=run_id,
        flow_version="3",
        mode=mode,
        status="committed",
        chapter_ref=f"chapter_{chapter_number}" if chapter_number else None,
        chapter_number=chapter_number,
        seeded=True,
        seeded_from_flow="2",
        notes=list(notes or ["migrated from flow v2 preserving old artifacts"]),
        created_at_utc=_utc_now(),
        committed_at_utc=_utc_now(),
    )
    _atomic_write_json(output_dir / RUN_MANIFEST_FILENAME, seed.model_dump(mode="json"))
    return seed


def _archive_manifest_snapshot(output_dir: Path, manifest: RunManifest) -> None:
    """把已完成 run 的 manifest 快照追加到 run_history/（审计，尽力而为）.

    在新章节启动新 run 前归档旧 run 的提交记录，使 run_manifest.json 成为
    当前 run 的活动记录，同时保留历史提交链（inspect-run/recover 仍可查）。
    """
    try:
        hist_dir = output_dir / RUN_HISTORY_DIR
        hist_dir.mkdir(parents=True, exist_ok=True)
        ts = (manifest.committed_at_utc or _utc_now()).replace(":", "").replace("T", "-")
        suffix = uuid.uuid4().hex[:6]
        _atomic_write_json(
            hist_dir / f"{manifest.run_id}-{ts}-{suffix}.json",
            manifest.model_dump(mode="json"),
        )
    except OSError:
        # 归档失败不阻断新 run 启动（活动 manifest 即将由新 run 原子覆盖）
        pass


def set_run_status(
    output_dir: Path,
    *,
    run_id: str,
    mode: Mode,
    status: RunStatus,
    chapter_number: int | None = None,
    notes: list[str] | None = None,
) -> RunManifest | None:
    """幂等推进五态状态机；flow v2 一律 no-op（不产生 manifest）。

    同 run_id 严格按迁移表推进（终态后非法迁移报错——防同一章被重复提交）；
    **新 run_id + 旧 run 终态**（提交完一章续写下一章）→ 归档旧 run 的提交
    记录到 run_history/，从新 run 重新开始（多章连续叙事的 run 生命周期）。

    flow v2 工作区保持旧语义（零成本契约：不新增产物、不改字节）；
    仅 flow v3 才写 run_manifest.json。
    """
    if read_flow_version(output_dir) != "3":
        return None

    manifest = read_run_manifest(output_dir)
    if manifest is None:
        manifest = RunManifest(
            run_id=run_id,
            flow_version="3",
            mode=mode,
            status=status,
            chapter_number=chapter_number,
            chapter_ref=f"chapter_{chapter_number}" if chapter_number else None,
            notes=list(notes or []),
            created_at_utc=_utc_now(),
        )
    elif manifest.run_id != run_id and manifest.status in ("committed", "rejected"):
        # 新章节新 run：归档已完成/拒绝的旧 run，从新 run 重新开始。
        _archive_manifest_snapshot(output_dir, manifest)
        manifest = RunManifest(
            run_id=run_id,
            flow_version="3",
            mode=mode,
            status=status,
            chapter_number=chapter_number,
            chapter_ref=f"chapter_{chapter_number}" if chapter_number else None,
            notes=list(notes or []) + [f"archived prior run {manifest.run_id} ({manifest.status})"],
            created_at_utc=_utc_now(),
        )
    else:
        if not manifest.transition_allowed(status):
            raise ValueError(
                f"illegal run status transition: {manifest.status} -> {status}"
            )
        manifest = manifest.model_copy(
            update={
                "status": status,
                "chapter_number": chapter_number or manifest.chapter_number,
                "chapter_ref": (
                    f"chapter_{chapter_number}" if chapter_number else manifest.chapter_ref
                ),
            }
        )
        if notes:
            manifest.notes = list(manifest.notes) + list(notes)
    _atomic_write_json(output_dir / RUN_MANIFEST_FILENAME, manifest.model_dump(mode="json"))
    return manifest


class ChapterCommitBoundary:
    """事务式章节提交边界：正文/状态/Frame 绑定同一提交记录，崩溃可恢复.

    Parameters
    ----------
    output_dir : Path
        流输出目录（output/<compose|extend>），manifest 与 .flow_version 所在。
    chapters_dir : Path | None
        正文目录（novel/chapters）；缺省从 output_dir.parent.parent / 'chapters' 推导。
    failpoint : Callable[[str], None] | None
        测试注入：在指定写步骤前抛错模拟崩溃（步骤见 FAILPOINT_STEPS）。
    """

    def __init__(
        self,
        output_dir: Path,
        chapters_dir: Path | None = None,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.novel_dir = self.output_dir.parent.parent
        self.chapters_dir = Path(chapters_dir) if chapters_dir else (
            self.novel_dir / "chapters"
        )
        self.failpoint = failpoint
        self.manifest_path = self.output_dir / RUN_MANIFEST_FILENAME

    # ---- 路径辅助 ----
    def _rel(self, path: Path) -> str:
        return os.path.relpath(str(path), str(self.novel_dir)).replace(os.sep, "/")

    def _touch_failpoint(self, step: str) -> None:
        if self.failpoint is not None:
            self.failpoint(step)

    # ---- 提交 ----
    def commit(
        self,
        *,
        run_id: str,
        mode: Mode,
        chapter_number: int,
        chapter_text: str,
        state_path: Path,
        state_json: str,
        frames_path: Path,
        frames_json: str,
        archive_text: str | None = None,
        provenance_json: str | None = None,
        orchestration_state_json: str | None = None,
        orchestration_history_json: str | None = None,
        prev_chapter_ref: str | None = None,
        source_text_hash: str | None = None,
        facts_package_hash: str | None = None,
        review_route: str | None = None,
        notes: list[str] | None = None,
    ) -> CommitResult:
        """把一章的 正文+归档+provenance+Frame+状态包+编排状态 绑定为一次原子提交.

        产物全部落盘后，manifest（提交记录）最后原子写入；任一产物写入失败
        （含 failpoint 注入的崩溃）→ manifest 不落盘 → 重启 recover() 不识别。
        """
        chapter_file = self.chapters_dir / f"chapter_{chapter_number}.txt"
        if chapter_file.exists():
            raise UnmanagedArtifactError(
                f"unmanaged chapter artifact already exists: {chapter_file}; "
                "resolve via `novel inspect-run` before committing (refuse overwrite)"
            )

        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        state_path = Path(state_path)
        frames_path = Path(frames_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        frames_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 1. 正文写入
            self._touch_failpoint("chapter")
            chapter_file.write_text(chapter_text, encoding="utf-8")

            # 2. 归档（prose_history/draft_chapter_N.txt）
            if archive_text is not None:
                self._touch_failpoint("archive")
                archive_path = self.output_dir / "prose_history" / f"draft_chapter_{chapter_number}.txt"
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                archive_path.write_text(archive_text, encoding="utf-8")

            # 3. provenance（chapter_provenance.json，随 commit 一起落盘）
            if provenance_json is not None:
                self._touch_failpoint("provenance")
                (self.output_dir / "chapter_provenance.json").write_text(
                    provenance_json, encoding="utf-8"
                )

            # 4. Frame 推进
            self._touch_failpoint("frames")
            frames_path.write_text(frames_json, encoding="utf-8")

            # 5. 状态写入（state_before 在覆盖前取）
            state_before_hash = hash_file_if_exists(state_path)
            self._touch_failpoint("state")
            state_path.write_text(state_json, encoding="utf-8")

            # 6. 编排状态与历史原子写入
            if orchestration_state_json is not None or orchestration_history_json is not None:
                self._touch_failpoint("orchestration")
                if orchestration_state_json is not None:
                    orch_state_path = self.output_dir / "committed_orchestration_state.json"
                    orch_state_path.parent.mkdir(parents=True, exist_ok=True)
                    orch_state_path.write_text(orchestration_state_json, encoding="utf-8")
                if orchestration_history_json is not None:
                    orch_hist_path = self.output_dir / "orchestration_history.json"
                    orch_hist_path.parent.mkdir(parents=True, exist_ok=True)
                    orch_hist_path.write_text(orchestration_history_json, encoding="utf-8")
        except Exception:
            # 模拟崩溃 / 真实 IO 失败：manifest 未落盘，不算提交。
            raise

        # 计算全部产物哈希
        artifacts: dict[str, str] = {}
        artifacts[self._rel(chapter_file)] = sha256_file(chapter_file)
        if archive_text is not None:
            artifacts[self._rel(self.output_dir / "prose_history" / f"draft_chapter_{chapter_number}.txt")] = (
                sha256_file(self.output_dir / "prose_history" / f"draft_chapter_{chapter_number}.txt")
            )
        if provenance_json is not None:
            artifacts[self._rel(self.output_dir / "chapter_provenance.json")] = sha256_file(
                self.output_dir / "chapter_provenance.json"
            )
        artifacts[self._rel(frames_path)] = sha256_file(frames_path)
        artifacts[self._rel(state_path)] = sha256_file(state_path)
        if orchestration_state_json is not None:
            orch_state_path = self.output_dir / "committed_orchestration_state.json"
            artifacts[self._rel(orch_state_path)] = sha256_file(orch_state_path)
        if orchestration_history_json is not None:
            orch_hist_path = self.output_dir / "orchestration_history.json"
            artifacts[self._rel(orch_hist_path)] = sha256_file(orch_hist_path)

        prev_chapter_hash = None
        if prev_chapter_ref:
            prev_file = self.chapters_dir / f"{prev_chapter_ref}.txt"
            prev_chapter_hash = hash_file_if_exists(prev_file)

        manifest = RunManifest(
            run_id=run_id,
            flow_version="3",
            kind="run",
            mode=mode,
            status="committed",
            chapter_ref=f"chapter_{chapter_number}",
            chapter_number=chapter_number,
            prev_chapter_ref=prev_chapter_ref,
            source_text_hash=source_text_hash,
            prev_chapter_hash=prev_chapter_hash,
            draft_hash=sha256_text(chapter_text),
            facts_package_hash=facts_package_hash,
            state_before_hash=state_before_hash,
            state_after_hash=sha256_file(state_path),
            frame_hash=sha256_file(frames_path),
            artifacts=artifacts,
            review_route=review_route,
            notes=list(notes or []),
            created_at_utc=_utc_now(),
            committed_at_utc=_utc_now(),
        )

        # 提交记录（manifest）最后原子写入
        self._touch_failpoint("manifest")
        _atomic_write_json(
            self.manifest_path,
            manifest.model_dump(mode="json"),
            before_replace=lambda: self._touch_failpoint("manifest.replace"),
        )

        # 审计副本（post-commit，失败不影响提交判定）
        self._finalize_history(manifest)

        return CommitResult(ok=True, run_manifest=manifest, artifacts=artifacts)

    def _finalize_history(self, manifest: RunManifest) -> None:
        """把 finalized manifest 快照追加到 run_history/（审计用，尽力而为）。"""
        try:
            hist_dir = self.output_dir / RUN_HISTORY_DIR
            hist_dir.mkdir(parents=True, exist_ok=True)
            ts = (manifest.committed_at_utc or _utc_now()).replace(":", "").replace("T", "-")
            suffix = uuid.uuid4().hex[:6]
            _atomic_write_json(
                hist_dir / f"{manifest.run_id}-{ts}-{suffix}.json",
                manifest.model_dump(mode="json"),
            )
        except OSError:
            # 审计副本失败不阻断已完成的提交（manifest 已是权威提交记录）
            pass

    # ---- 崩溃恢复 ----
    def recover(self) -> RecoveryReport:
        """重启恢复判定：只识别「manifest 存在 + 全产物哈希一致」的完整提交.

        返回 recognized=False 的任意原因都表示：**不要**把磁盘上的产物当作
        合法链头继续——正文可能已存在但状态未更新，或反之。孤儿 chapter 文件
        一并列出，由操作者经 `novel inspect-run` 处理。
        """
        stale_tmp = [
            str(p)
            for p in self.output_dir.glob(f"{RUN_MANIFEST_FILENAME}{_TMP_SUFFIX}")
        ]

        manifest = read_run_manifest(self.output_dir)
        if manifest is None:
            # 无提交记录：任何 chapter 文件都无 v3 覆盖，一律不识别为已提交。
            unmanaged = sorted(
                str(p)
                for p in self.chapters_dir.glob("chapter_*.txt")
                if _parse_chapter_number(p) is not None
            )
            return RecoveryReport(
                recognized=False,
                reason="no_manifest",
                manifest=None,
                orphans=unmanaged,
                stale_tmp=stale_tmp,
            )

        if manifest.status != "committed":
            return RecoveryReport(
                recognized=False,
                reason=f"status_{manifest.status}",
                manifest=manifest,
                orphans=self._scan_orphans(manifest),
                stale_tmp=stale_tmp,
            )

        missing: list[str] = []
        mismatched: list[dict] = []
        for rel, expected in manifest.artifacts.items():
            path = self.novel_dir / rel
            if not path.exists():
                missing.append(rel)
                continue
            actual = sha256_file(path)
            if actual != expected:
                mismatched.append({"path": rel, "expected": expected, "actual": actual})

        if missing or mismatched:
            return RecoveryReport(
                recognized=False,
                reason="artifact_missing" if missing else "artifact_mismatch",
                manifest=manifest,
                missing=missing,
                mismatched=mismatched,
                orphans=self._scan_orphans(manifest),
                stale_tmp=stale_tmp,
            )

        return RecoveryReport(
            recognized=True,
            reason="committed",
            manifest=manifest,
            orphans=self._scan_orphans(manifest),
            stale_tmp=stale_tmp,
        )

    def _scan_orphans(self, manifest: RunManifest) -> list[str]:
        """扫描未被提交链覆盖的 chapter 文件（编号 > 链头 = 崩溃遗留孤儿）。"""
        head = manifest.chapter_number
        if head is None:
            return []
        return sorted(
            str(p)
            for p in self.chapters_dir.glob("chapter_*.txt")
            if (_parse_chapter_number(p) or 0) > head
        )

    # ---- 巡检 ----
    def inspect(self) -> dict:
        """结构化巡检：flow 版本 + 提交记录 + 恢复判定 + 运行史。"""
        history = []
        hist_dir = self.output_dir / RUN_HISTORY_DIR
        if hist_dir.exists():
            for p in sorted(hist_dir.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    history.append(
                        {
                            "file": p.name,
                            "run_id": data.get("run_id"),
                            "status": data.get("status"),
                            "chapter_ref": data.get("chapter_ref"),
                            "committed_at_utc": data.get("committed_at_utc"),
                        }
                    )
                except (OSError, json.JSONDecodeError):
                    continue
        report = self.recover()
        return {
            "novel_dir": str(self.novel_dir),
            "output_dir": str(self.output_dir),
            "flow_version": read_flow_version(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "manifest": (
                report.manifest.model_dump(mode="json")
                if report.manifest is not None
                else None
            ),
            "recovery": report.model_dump(mode="json"),
            "run_history": history,
        }


def _parse_chapter_number(path: Path) -> int | None:
    stem = path.stem
    if not stem.startswith("chapter_"):
        return None
    try:
        return int(stem[len("chapter_"):])
    except ValueError:
        return None


def _atomic_write_json(
    path: Path, data: dict, before_replace: Callable[[], None] | None = None
) -> None:
    """原子写 JSON：先写 tmp，再 os.replace 到目标（同卷替换，崩溃不留半文件）。

    before_replace 供测试在「tmp 已写、replace 前」注入崩溃——验证 manifest
    未替换成功时（遗留 .tmp、无正式文件）提交不被识别。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + _TMP_SUFFIX)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if before_replace is not None:
        before_replace()
    os.replace(tmp, path)
