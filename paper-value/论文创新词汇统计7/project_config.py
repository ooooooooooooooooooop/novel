import json
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "configs"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_project_config(config_path: str = None) -> Dict[str, Any]:
    default_paths = _load_json(CONFIG_DIR / "paths.default.json")
    default_runtime = _load_json(CONFIG_DIR / "runtime.default.json")

    cfg: Dict[str, Any] = {
        "paths": default_paths,
        "runtime": default_runtime,
    }

    if config_path:
        user_cfg = _load_json(Path(config_path))
        cfg = _deep_merge(cfg, user_cfg)

    return cfg


def resolve_project_path(path_str: str) -> str:
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    return str((PROJECT_ROOT / path).resolve())


def get_paths(cfg: Dict[str, Any]) -> Dict[str, str]:
    paths = cfg.get("paths", {})
    return {k: resolve_project_path(v) for k, v in paths.items() if isinstance(v, str)}


def get_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return dict(cfg.get("runtime", {}))


def get_years(runtime: Dict[str, Any]) -> range:
    start = int(runtime.get("year_start", 2010))
    end = int(runtime.get("year_end", 2025))
    return range(start, end + 1)
