# P6 Observation Protocol (14d/30d)

## Window

- Start: 2026-02-10 UTC
- Data source: `paths.compat_usage_log_path` (default `artifacts/runtime/logs/compat_launcher_usage.jsonl`)
- Noise policy: exclude `--help/-h` calls by default

## Daily/Weekly Commands

```powershell
# one-shot snapshot (recommended, writes json+md+history)
python tools/compat_observation_snapshot.py --days 14,30 --min-calls 1

# 14-day view (default excludes --help)
python tools/compat_usage_report.py --days 14 --min-calls 1

# 30-day view
python tools/compat_usage_report.py --days 30 --min-calls 1

# Save machine-readable snapshots
python tools/compat_usage_report.py --days 14 --min-calls 1 --json-output artifacts/runtime/logs/compat_window_14d.json
python tools/compat_usage_report.py --days 30 --min-calls 1 --json-output artifacts/runtime/logs/compat_window_30d.json
```

## Gate Criteria

### Gate A (14d, staged enforcement)

- For one selected launcher, real call count is `0` in 14d window.
- Then enable targeted blocklist for trial:

```powershell
$env:PROJECT_COMPAT_BLOCKLIST='query_paper.py'
python query_paper.py --help   # expect exit code 2
```

### Gate B (30d, removal candidate)

- For a launcher, real call count is `0` in 30d window.
- No new operational incident linked to canonical replacement path.
- Then enter removal batch candidate set.

### Gate C (full removal of 4 critical launchers)

- All 4 launchers meet Gate B.
- `PROJECT_COMPAT_MODE=error` full-mode trial passes expected checks.
- Docs and `health_check` already point to canonical commands.

## Rollback

```powershell
# Global rollback
Remove-Item Env:PROJECT_COMPAT_MODE -ErrorAction SilentlyContinue

# Targeted rollback
Remove-Item Env:PROJECT_COMPAT_BLOCKLIST -ErrorAction SilentlyContinue
```

## Notes

- Current window starts after log rotation completed on 2026-02-10.
- Previous data archived at:
  - `artifacts/runtime/logs/archive/compat_launcher_usage_pre_p6_window_20260210T021046Z.jsonl`
- Gate A execution template:
  - `.taskflow/active/project-reorg-phase6/gate-a-checklist-2026-02-24.md`
