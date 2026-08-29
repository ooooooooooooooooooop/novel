"""S1（54 计划）契约测试：--auto 标志解析与 A1 自动通路转发。

验证：
1. audit/extend/compose 三个子命令接受 --auto 标志（help 可见）
2. --auto 时 _auto_or_staged 转发到 _run_auto（extend/compose），参数正确
3. --auto 缺 policy/profile 环境变量时明确报错（不静默）
4. audit --auto 明确拒绝（A1 自动通路仅支持生成流）
5. 无 --auto 时返回 None，staged 路径零改动
"""
from __future__ import annotations

import argparse
import contextlib
import io
from types import SimpleNamespace

import pytest

import src.novel_cli as nc


def _parse(cmd: str, *extra: str) -> argparse.Namespace:
    return nc.build_parser().parse_args([cmd, "测试小说", *extra])


def test_auto_flag_accepted_by_all_flows() -> None:
    for cmd in ("audit", "extend", "compose"):
        args = _parse(cmd, "--auto")
        assert args.auto is True


def test_help_shows_auto_flag() -> None:
    for cmd in ("audit", "extend", "compose"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            nc.build_parser().parse_args([cmd, "--help"])
        assert "--auto" in buf.getvalue(), f"{cmd} --help 缺少 --auto"


def test_without_auto_returns_none_staged_unchanged() -> None:
    args = argparse.Namespace(auto=False)
    assert nc._auto_or_staged(args, "extend") is None
    assert nc._auto_or_staged(args, "compose") is None
    assert nc._auto_or_staged(args, "audit") is None


def test_auto_without_policy_profile_errors(monkeypatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.delenv("NOVEL_AUTO_POLICY", raising=False)
    monkeypatch.delenv("NOVEL_AUTO_PROFILE", raising=False)
    args = argparse.Namespace(auto=True, novel="x")
    assert nc._auto_or_staged(args, "extend") == 1
    assert "NOVEL_AUTO_POLICY" in capsys.readouterr().out


def test_audit_auto_rejected(monkeypatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("NOVEL_AUTO_POLICY", "p.json")
    monkeypatch.setenv("NOVEL_AUTO_PROFILE", "f.json")
    args = argparse.Namespace(auto=True, novel="x")
    assert nc._auto_or_staged(args, "audit") == 1
    assert "不支持 --auto" in capsys.readouterr().out


def test_extend_auto_forwards_to_run_auto(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVEL_AUTO_POLICY", str(tmp_path / "policy.json"))
    monkeypatch.setenv("NOVEL_AUTO_PROFILE", str(tmp_path / "profile.json"))
    calls: list[argparse.Namespace] = []

    def fake_run_auto(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(nc, "_run_auto", fake_run_auto)
    args = SimpleNamespace(auto=True, novel="x", nsfw="off", input=None, style=None)
    assert nc._auto_or_staged(args, "extend") == 0
    assert len(calls) == 1
    assert calls[0].flow_mode == "extend"
    assert calls[0].run_name == "auto"
    assert calls[0].policy == str(tmp_path / "policy.json")
    assert calls[0].profile == str(tmp_path / "profile.json")


def test_compose_auto_forwards_to_run_auto(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVEL_AUTO_POLICY", str(tmp_path / "policy.json"))
    monkeypatch.setenv("NOVEL_AUTO_PROFILE", str(tmp_path / "profile.json"))
    calls: list[argparse.Namespace] = []

    def fake_run_auto(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(nc, "_run_auto", fake_run_auto)
    args = SimpleNamespace(auto=True, novel="x", nsfw="off", input=None, style=None)
    assert nc._auto_or_staged(args, "compose") == 0
    assert calls and calls[0].flow_mode == "compose"
